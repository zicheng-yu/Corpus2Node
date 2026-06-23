"""Offline course-processing workflow: ingest -> extract -> build -> save (LangGraph).

The LLM, embedding and ingest seams are injectable so the whole pipeline can run
offline in tests. CPU-bound work (embedding, deterministic build) is pushed off the
event loop with asyncio.to_thread; extraction is natively async + concurrent.
State stays tiny (ids + counts); chunks/candidates/graph live in artifacts on disk.
"""
from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from corpus2node.core.clock import utcnow
from typing import TypedDict
from uuid import UUID

from langchain_core.embeddings import Embeddings
from langgraph.graph import END, START, StateGraph

from corpus2node.config import settings
from corpus2node.core.types import GraphArtifact, IngestArtifact, SessionStatus, SourceFile
from corpus2node.graph.build import build_graph_artifact
from corpus2node.graph.extract import AStructured, extract_graph_candidates, make_astructured
from corpus2node.graph.schemas import GraphExtractionResult
from corpus2node.index.embeddings import get_embeddings
from corpus2node.ingest.chunk import make_chunks_from_blocks
from corpus2node.llm import factory
from corpus2node.llm.credentials import Purpose
from corpus2node.storage import local

logger = logging.getLogger(__name__)

ExtractBlocks = Callable[[SourceFile], list[str]]


class WorkflowState(TypedDict):
    session_id: str
    chunk_count: int
    concept_count: int
    relation_count: int
    cluster_count: int


def default_extract_blocks(source: SourceFile) -> list[str]:
    from corpus2node.ingest.adapters import extract_blocks_for

    return extract_blocks_for(source)


def build_workflow(*, astructured: AStructured, embeddings: Embeddings, extract_blocks: ExtractBlocks):
    """Compile the ingest -> extract -> build StateGraph with the given seams bound."""

    async def ingest(state: WorkflowState) -> dict[str, int]:
        session_id = UUID(state["session_id"])
        session = local.load_session(session_id)
        pending = [source for source in session.source_files if not source.ingested]
        for source in pending:
            chunks = await asyncio.to_thread(_ingest_source, source, extract_blocks, embeddings)
            local.save_ingest_artifact(
                IngestArtifact(session_id=session_id, source_id=source.source_id, source_kind=source.kind, chunks=chunks)
            )
            source.ingested = True
        session.updated_at = utcnow()
        local.save_session(session)
        total = sum(len(artifact.chunks) for artifact in local.list_ingest_artifacts(session_id))
        logger.info("ingest: %d chunks from %d source(s)", total, len(pending))
        return {"chunk_count": total}

    async def extract(state: WorkflowState) -> dict[str, int]:
        session_id = UUID(state["session_id"])
        chunks = [chunk for artifact in local.list_ingest_artifacts(session_id) for chunk in artifact.chunks]
        if not chunks:
            raise ValueError("No chunks available for extraction. Did ingestion produce any text?")
        candidates = await extract_graph_candidates(
            chunks,
            astructured=astructured,
            max_concurrency=settings.extract_max_concurrency,
            batch_max_chars=settings.extract_batch_max_chars,
            batch_max_chunks=settings.extract_batch_max_chunks,
        )
        _save_candidates(session_id, candidates)
        logger.info("extract: %d concepts, %d relations", len(candidates.concepts), len(candidates.relations))
        return {"concept_count": len(candidates.concepts), "relation_count": len(candidates.relations)}

    async def build(state: WorkflowState) -> dict[str, int]:
        session_id = UUID(state["session_id"])
        chunks = [chunk for artifact in local.list_ingest_artifacts(session_id) for chunk in artifact.chunks]
        candidates = _load_candidates(session_id)
        graph = await asyncio.to_thread(
            build_graph_artifact, session_id, chunks, candidates, embeddings=embeddings
        )
        local.save_graph_artifact(graph)
        logger.info(
            "build: %d concepts, %d edges, %d clusters",
            len(graph.concepts), len(graph.edges), len(graph.topic_clusters),
        )
        return {
            "concept_count": len(graph.concepts),
            "relation_count": len(graph.edges),
            "cluster_count": len(graph.topic_clusters),
        }

    graph = StateGraph(WorkflowState)
    graph.add_node("ingest", ingest)
    graph.add_node("extract", extract)
    graph.add_node("build", build)
    graph.add_edge(START, "ingest")
    graph.add_edge("ingest", "extract")
    graph.add_edge("extract", "build")
    graph.add_edge("build", END)
    return graph.compile()


async def run_workflow(
    session_id: UUID,
    *,
    astructured: AStructured | None = None,
    embeddings: Embeddings | None = None,
    extract_blocks: ExtractBlocks | None = None,
) -> GraphArtifact:
    """Run the full offline pipeline for a session and return the built graph."""
    session = local.load_session(session_id)
    if not session.source_files:
        raise ValueError("Session has no source files to process.")
    logger.info("workflow start: session=%s, sources=%d", session_id, len(session.source_files))

    embeddings = embeddings or get_embeddings()
    if astructured is None:
        method = factory.structured_output_method(Purpose.graph)
        astructured = make_astructured(factory.build_chat_model(Purpose.graph), method=method)
    extract_blocks = extract_blocks or default_extract_blocks

    session.status = SessionStatus.building_graph
    session.error_message = None
    session.updated_at = utcnow()
    local.save_session(session)

    workflow = build_workflow(astructured=astructured, embeddings=embeddings, extract_blocks=extract_blocks)
    try:
        final = await workflow.ainvoke(
            {"session_id": str(session_id), "chunk_count": 0, "concept_count": 0, "relation_count": 0, "cluster_count": 0}
        )
    except Exception as exc:
        failed = local.load_session(session_id)
        failed.status = SessionStatus.failed
        failed.error_message = str(exc)
        failed.updated_at = utcnow()
        local.save_session(failed)
        raise

    graph = local.load_graph_artifact(session_id)
    session = local.load_session(session_id)
    session.status = SessionStatus.graph_ready
    session.error_message = None
    session.stats.chunk_count = final.get("chunk_count", 0)
    session.stats.concept_count = len(graph.concepts)
    session.stats.relation_count = len(graph.edges)
    session.stats.cluster_count = len(graph.topic_clusters)
    session.updated_at = utcnow()
    local.save_session(session)
    logger.info(
        "workflow done: session=%s concepts=%d edges=%d clusters=%d",
        session_id, len(graph.concepts), len(graph.edges), len(graph.topic_clusters),
    )
    return graph


def _ingest_source(source: SourceFile, extract_blocks: ExtractBlocks, embeddings: Embeddings):
    blocks = extract_blocks(source)
    chunks = make_chunks_from_blocks(str(source.source_id), source.kind, blocks)
    if chunks:
        vectors = embeddings.embed_documents([chunk.text for chunk in chunks])
        for chunk, vector in zip(chunks, vectors):
            chunk.embedding = list(vector)
    return chunks


def _candidates_path(session_id: UUID):
    return local.session_dir(session_id) / "graph_candidates.json"


def _save_candidates(session_id: UUID, candidates: GraphExtractionResult) -> None:
    _candidates_path(session_id).write_text(candidates.model_dump_json(indent=2), encoding="utf-8")


def _load_candidates(session_id: UUID) -> GraphExtractionResult:
    return GraphExtractionResult.model_validate_json(_candidates_path(session_id).read_text(encoding="utf-8"))
