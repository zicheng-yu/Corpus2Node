"""Offline course-processing workflow: ingest -> extract -> critic -> build (LangGraph).

The LLM, critic, embedding and ingest seams are injectable so the whole pipeline can
run offline in tests. CPU-bound work (embedding, deterministic build) is pushed off the
event loop with asyncio.to_thread; extraction + critic are natively async + concurrent.
State stays tiny (ids + counts); chunks/candidates/graph live in artifacts on disk.

Every node is wrapped by a RunRecorder, which captures per-node duration, chat-model
token usage and (for the critic) repair counts into a WorkflowRunArtifact saved per run.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
from collections.abc import AsyncIterator, Callable
from typing import TypedDict
from uuid import UUID

from langchain_core.embeddings import Embeddings
from langgraph.graph import END, START, StateGraph

from corpus2node.config import settings
from corpus2node.core.clock import utcnow
from corpus2node.core.types import (
    ArtifactProvenance,
    EvidenceChunk,
    GraphArtifact,
    IngestArtifact,
    SessionStatus,
    SourceFile,
)
from corpus2node.graph.build import build_graph_artifact
from corpus2node.graph.critic import (
    CRITIC_SYSTEM_PROMPT,
    ACritic,
    apply_repair,
    critique_candidates,
    make_acritic,
)
from corpus2node.graph.extract import AStructured, extract_graph_candidates, make_astructured
from corpus2node.graph.prompts import GRAPH_SYSTEM_PROMPT
from corpus2node.graph.schemas import GraphCriticReport, GraphExtractionResult
from corpus2node.index.embeddings import embedding_signature, get_embeddings
from corpus2node.ingest.chunk import make_chunks_from_blocks
from corpus2node.llm import factory
from corpus2node.llm.credentials import Purpose
from corpus2node.storage import local
from corpus2node.storage.run_artifact import RunRecorder, save_run_artifact

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


def build_workflow(
    *,
    astructured: AStructured,
    acritic: ACritic | None,
    embeddings: Embeddings,
    extract_blocks: ExtractBlocks,
    recorder: RunRecorder,
    provenance: ArtifactProvenance,
):
    """Compile the ingest -> extract -> critic -> build StateGraph with the given seams bound."""

    async def ingest(state: WorkflowState) -> dict[str, int]:
        async with recorder.node("ingest") as run:
            session_id = UUID(state["session_id"])
            session = local.load_session(session_id)
            pending: list[SourceFile] = []
            for source in session.source_files:
                source_hash = provenance.source_hashes[str(source.source_id)]
                artifact = _load_ingest_artifact_or_none(session_id, source)
                needs_extract = artifact is None or artifact.source_sha256 != source_hash
                needs_embedding = (
                    needs_extract
                    or artifact.embedding_signature != provenance.embedding_signature
                    or any(not chunk.embedding for chunk in artifact.chunks)
                )
                if not needs_extract and not needs_embedding:
                    source.ingested = True
                    source.ingest_artifact_path = str(local.ingest_path(session_id, source.source_id))
                    continue
                pending.append(source)
                if needs_extract:
                    chunks = await asyncio.to_thread(_ingest_source, source, extract_blocks, embeddings)
                else:
                    chunks = await asyncio.to_thread(_reembed_chunks, artifact.chunks, embeddings)
                local.save_ingest_artifact(
                    IngestArtifact(
                        session_id=session_id,
                        source_id=source.source_id,
                        source_kind=source.kind,
                        chunks=chunks,
                        source_sha256=source_hash,
                        embedding_signature=provenance.embedding_signature,
                    )
                )
                source.ingested = True
                source.ingest_artifact_path = str(local.ingest_path(session_id, source.source_id))
            session.updated_at = utcnow()
            local.save_session(session)
            total = sum(len(artifact.chunks) for artifact in local.list_ingest_artifacts(session_id))
            run.detail = {"chunks": total, "sources": len(pending)}
            logger.info("ingest: %d chunks from %d source(s)", total, len(pending))
            return {"chunk_count": total}

    async def extract(state: WorkflowState) -> dict[str, int]:
        async with recorder.node("extract") as run:
            session_id = UUID(state["session_id"])
            chunks = [chunk for artifact in local.list_ingest_artifacts(session_id) for chunk in artifact.chunks]
            if not chunks:
                raise ValueError("No chunks available for extraction. Did ingestion produce any text?")
            candidates = await extract_graph_candidates(
                chunks,
                astructured=astructured,
                max_concurrency=factory.concurrency_for(Purpose.graph, settings.extract_max_concurrency),
                batch_max_chars=settings.extract_batch_max_chars,
                batch_max_chunks=settings.extract_batch_max_chunks,
            )
            _save_candidates(session_id, candidates)
            run.detail = {"concepts": len(candidates.concepts), "relations": len(candidates.relations)}
            logger.info("extract: %d concepts, %d relations", len(candidates.concepts), len(candidates.relations))
            return {"concept_count": len(candidates.concepts), "relation_count": len(candidates.relations)}

    async def critic(state: WorkflowState) -> dict[str, int]:
        async with recorder.node("critic") as run:
            session_id = UUID(state["session_id"])
            if not settings.graph_critic_enabled or acritic is None:
                run.detail = {"skipped": True}
                return {}
            candidates = _load_candidates(session_id)
            chunks = [chunk for artifact in local.list_ingest_artifacts(session_id) for chunk in artifact.chunks]
            report = await critique_candidates(
                candidates, chunks, embeddings,
                acritic=acritic,
                batch_concepts=settings.critic_batch_concepts,
                batch_relations=settings.critic_batch_relations,
                max_concurrency=factory.concurrency_for(Purpose.critic, settings.extract_max_concurrency),
            )
            repaired, stats = apply_repair(candidates, report)
            _save_candidates(session_id, repaired)
            _save_critic_report(session_id, report)
            run.repair_count = stats.total
            run.detail = {**stats.as_dict(), "concepts": len(repaired.concepts), "relations": len(repaired.relations)}
            logger.info(
                "critic: repaired %d items -> %d concepts, %d relations",
                stats.total, len(repaired.concepts), len(repaired.relations),
            )
            return {"concept_count": len(repaired.concepts), "relation_count": len(repaired.relations)}

    async def build(state: WorkflowState) -> dict[str, int]:
        async with recorder.node("build") as run:
            session_id = UUID(state["session_id"])
            chunks = [chunk for artifact in local.list_ingest_artifacts(session_id) for chunk in artifact.chunks]
            candidates = _load_candidates(session_id)
            graph = await asyncio.to_thread(
                build_graph_artifact, session_id, chunks, candidates, embeddings=embeddings
            )
            graph.provenance = provenance
            local.save_graph_artifact(graph)
            run.detail = {"concepts": len(graph.concepts), "edges": len(graph.edges), "clusters": len(graph.topic_clusters)}
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
    graph.add_node("critic", critic)
    graph.add_node("build", build)
    graph.add_edge(START, "ingest")
    graph.add_edge("ingest", "extract")
    graph.add_edge("extract", "critic")
    graph.add_edge("critic", "build")
    graph.add_edge("build", END)
    return graph.compile()


def _resolve_acritic(acritic: ACritic | None) -> ACritic | None:
    """Build the critic seam from the registry when enabled and not injected."""
    if acritic is not None or not settings.graph_critic_enabled:
        return acritic
    method = factory.structured_output_method(Purpose.critic)
    return make_acritic(factory.build_chat_model(Purpose.critic), method=method)


async def run_workflow(
    session_id: UUID,
    *,
    astructured: AStructured | None = None,
    acritic: ACritic | None = None,
    embeddings: Embeddings | None = None,
    extract_blocks: ExtractBlocks | None = None,
    force: bool = False,
) -> GraphArtifact:
    """Run the full offline pipeline for a session and return the built graph."""
    session = local.load_session(session_id)
    if not session.source_files:
        raise ValueError("Session has no source files to process.")
    embeddings = embeddings or get_embeddings()
    provenance = _build_provenance(session, embeddings)
    if not force:
        cached = _load_valid_cached_graph(session, provenance)
        if cached is not None:
            return cached
    logger.info("workflow start: session=%s, sources=%d", session_id, len(session.source_files))

    if astructured is None:
        method = factory.structured_output_method(Purpose.graph)
        astructured = make_astructured(factory.build_chat_model(Purpose.graph), method=method)
    acritic = _resolve_acritic(acritic)
    extract_blocks = extract_blocks or default_extract_blocks

    session.status = SessionStatus.building_graph
    session.error_message = None
    session.updated_at = utcnow()
    local.save_session(session)

    recorder = RunRecorder(session_id)
    workflow = build_workflow(
        astructured=astructured,
        acritic=acritic,
        embeddings=embeddings,
        extract_blocks=extract_blocks,
        recorder=recorder,
        provenance=provenance,
    )
    try:
        final = await workflow.ainvoke(
            {"session_id": str(session_id), "chunk_count": 0, "concept_count": 0, "relation_count": 0, "cluster_count": 0}
        )
    except Exception as exc:
        save_run_artifact(recorder.finalize("failed", str(exc)))
        failed = local.load_session(session_id)
        failed.status = SessionStatus.failed
        failed.error_message = str(exc)
        failed.updated_at = utcnow()
        local.save_session(failed)
        raise

    save_run_artifact(recorder.finalize("succeeded"))
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
        "workflow done: session=%s concepts=%d edges=%d clusters=%d tokens=%d",
        session_id, len(graph.concepts), len(graph.edges), len(graph.topic_clusters), recorder.artifact.total_tokens,
    )
    return graph


_NODE_STAGE = {"ingest": "ingest", "extract": "extract", "critic": "critic", "build": "build"}


async def stream_workflow(
    session_id: UUID,
    *,
    astructured: AStructured | None = None,
    acritic: ACritic | None = None,
    embeddings: Embeddings | None = None,
    extract_blocks: ExtractBlocks | None = None,
    force: bool = False,
) -> AsyncIterator[dict]:
    """Run the pipeline, yielding a real event after each node so the UI reflects
    actual progress (instead of a fake 0→done jump). Idempotent: a session that's
    already graph_ready emits the existing counts without re-running."""
    session = local.load_session(session_id)
    if not session.source_files:
        raise ValueError("Session has no source files to process.")

    embeddings = embeddings or get_embeddings()
    provenance = _build_provenance(session, embeddings)
    if not force:
        graph = _load_valid_cached_graph(session, provenance)
    else:
        graph = None
    if graph is not None:
        if session.stats.chunk_count == 0:
            session.stats.chunk_count = _chunk_count(session_id)
            session.updated_at = utcnow()
            local.save_session(session)
        yield {"type": "done", "data": {
            "chunk_count": session.stats.chunk_count,
            "concept_count": len(graph.concepts),
            "relation_count": len(graph.edges),
            "cluster_count": len(graph.topic_clusters),
            "cached": True,
        }}
        return

    extract_blocks = extract_blocks or default_extract_blocks
    if astructured is None:
        method = factory.structured_output_method(Purpose.graph)
        astructured = make_astructured(factory.build_chat_model(Purpose.graph), method=method)
    acritic = _resolve_acritic(acritic)
    session.status = SessionStatus.building_graph
    session.error_message = None
    session.updated_at = utcnow()
    local.save_session(session)
    logger.info("workflow stream start: session=%s", session_id)

    recorder = RunRecorder(session_id)
    workflow = build_workflow(
        astructured=astructured,
        acritic=acritic,
        embeddings=embeddings,
        extract_blocks=extract_blocks,
        recorder=recorder,
        provenance=provenance,
    )
    state0 = {"session_id": str(session_id), "chunk_count": 0, "concept_count": 0, "relation_count": 0, "cluster_count": 0}
    try:
        yield {"type": "start", "data": {}}
        async for update in workflow.astream(state0, stream_mode="updates"):
            for node, delta in update.items():
                yield {"type": "step", "data": {
                    "node": _NODE_STAGE.get(node, node), **(delta or {}), "metrics": _node_metrics(recorder, node),
                }}
    except Exception as exc:
        save_run_artifact(recorder.finalize("failed", str(exc)))
        failed = local.load_session(session_id)
        failed.status = SessionStatus.failed
        failed.error_message = str(exc)
        failed.updated_at = utcnow()
        local.save_session(failed)
        logger.exception("workflow stream failed: session=%s", session_id)
        yield {"type": "error", "data": {"message": str(exc)}}
        return

    save_run_artifact(recorder.finalize("succeeded"))
    graph = local.load_graph_artifact(session_id)
    final = local.load_session(session_id)
    final.status = SessionStatus.graph_ready
    final.error_message = None
    final.stats.chunk_count = _chunk_count(session_id)
    final.stats.concept_count = len(graph.concepts)
    final.stats.relation_count = len(graph.edges)
    final.stats.cluster_count = len(graph.topic_clusters)
    final.updated_at = utcnow()
    local.save_session(final)
    yield {"type": "done", "data": {
        "chunk_count": final.stats.chunk_count,
        "concept_count": len(graph.concepts),
        "relation_count": len(graph.edges),
        "cluster_count": len(graph.topic_clusters),
        "total_tokens": recorder.artifact.total_tokens,
        "duration_ms": recorder.artifact.duration_ms,
    }}


def _node_metrics(recorder: RunRecorder, node: str) -> dict:
    run = next((run for run in reversed(recorder.artifact.nodes) if run.node == node), None)
    if run is None:
        return {}
    return {"duration_ms": run.duration_ms, "total_tokens": run.total_tokens, "repair_count": run.repair_count}


def _ingest_source(source: SourceFile, extract_blocks: ExtractBlocks, embeddings: Embeddings):
    blocks = extract_blocks(source)
    chunks = make_chunks_from_blocks(str(source.source_id), source.kind, blocks)
    if chunks:
        vectors = embeddings.embed_documents([chunk.text for chunk in chunks])
        for chunk, vector in zip(chunks, vectors):
            chunk.embedding = list(vector)
    return chunks


async def ingest_sources_only(
    session_id: UUID, *, extract_blocks: ExtractBlocks | None = None
) -> int:
    """Prepare source chunks without graph extraction or embedding-model work.

    The scientific vertical uses this profile so an uploaded paper can be analysed
    without first paying for the generic knowledge-graph workflow.
    """
    extract_blocks = extract_blocks or default_extract_blocks
    session = local.load_session(session_id)
    if not session.source_files:
        if local.list_ingest_artifacts(session_id):
            return _chunk_count(session_id)
        raise ValueError("Session has no source files to process.")
    previous_status = session.status
    session.status = SessionStatus.ingesting
    session.updated_at = utcnow()
    local.save_session(session)
    try:
        for source in session.source_files:
            source_hash = _source_sha256(source)
            artifact = _load_ingest_artifact_or_none(session_id, source)
            if artifact is None or artifact.source_sha256 != source_hash:
                blocks = await asyncio.to_thread(extract_blocks, source)
                chunks = make_chunks_from_blocks(str(source.source_id), source.kind, blocks)
                artifact = IngestArtifact(
                    session_id=session_id,
                    source_id=source.source_id,
                    source_kind=source.kind,
                    chunks=chunks,
                    source_sha256=source_hash,
                    embedding_signature="none",
                )
                local.save_ingest_artifact(artifact)
            elif not artifact.source_sha256:
                artifact.source_sha256 = source_hash
                local.save_ingest_artifact(artifact)
            source.ingested = True
            source.ingest_artifact_path = str(local.ingest_path(session_id, source.source_id))
        session.stats.chunk_count = _chunk_count(session_id)
        session.status = (
            previous_status
            if previous_status in {SessionStatus.graph_ready, SessionStatus.notes_ready}
            else SessionStatus.ingested
        )
        session.error_message = None
        session.updated_at = utcnow()
        local.save_session(session)
        return session.stats.chunk_count
    except Exception as exc:
        session.status = SessionStatus.failed
        session.error_message = str(exc)
        session.updated_at = utcnow()
        local.save_session(session)
        raise


def _reembed_chunks(chunks: list[EvidenceChunk], embeddings: Embeddings) -> list[EvidenceChunk]:
    values = [chunk.model_copy(deep=True) for chunk in chunks]
    vectors = embeddings.embed_documents([chunk.text for chunk in values]) if values else []
    for chunk, vector in zip(values, vectors):
        chunk.embedding = list(vector)
    return values


def _load_ingest_artifact_or_none(session_id: UUID, source: SourceFile) -> IngestArtifact | None:
    try:
        return local.load_ingest_artifact(session_id, source.source_id)
    except FileNotFoundError:
        return None


def _source_sha256(source: SourceFile) -> str:
    if source.content_sha256:
        return source.content_sha256
    digest = hashlib.sha256()
    try:
        with open(source.storage_path, "rb") as handle:
            while block := handle.read(1024 * 1024):
                digest.update(block)
    except FileNotFoundError:
        digest.update(f"missing:{source.source_id}:{source.size_bytes}".encode())
    source.content_sha256 = digest.hexdigest()
    return source.content_sha256


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _build_provenance(session, embeddings: Embeddings) -> ArtifactProvenance:
    source_hashes = {str(source.source_id): _source_sha256(source) for source in session.source_files}
    local.save_session(session)
    config = {
        "extract_batch_max_chars": settings.extract_batch_max_chars,
        "extract_batch_max_chunks": settings.extract_batch_max_chunks,
        "graph_critic_enabled": settings.graph_critic_enabled,
        "critic_batch_concepts": settings.critic_batch_concepts,
        "critic_batch_relations": settings.critic_batch_relations,
    }
    return ArtifactProvenance(
        source_hashes=source_hashes,
        embedding_signature=embedding_signature(embeddings),
        graph_model_signature=factory.purpose_signature(Purpose.graph),
        critic_model_signature=(
            factory.purpose_signature(Purpose.critic) if settings.graph_critic_enabled else "disabled"
        ),
        graph_prompt_sha256=_sha256_text(GRAPH_SYSTEM_PROMPT),
        critic_prompt_sha256=_sha256_text(CRITIC_SYSTEM_PROMPT),
        config_sha256=_sha256_text(json.dumps(config, sort_keys=True)),
    )


def _load_valid_cached_graph(
    session, provenance: ArtifactProvenance
) -> GraphArtifact | None:
    try:
        graph = local.load_graph_artifact(session.session_id)
    except FileNotFoundError:
        return None
    if graph.provenance != provenance:
        logger.info("workflow cache invalidated: session=%s provenance changed", session.session_id)
        return None
    return graph


def load_valid_cached_graph(session_id: UUID, embeddings: Embeddings) -> GraphArtifact | None:
    """Public cache preflight used by the API before it resolves paid LLM clients."""
    session = local.load_session(session_id)
    if not session.source_files:
        return None
    return _load_valid_cached_graph(session, _build_provenance(session, embeddings))


def _candidates_path(session_id: UUID):
    return local.session_dir(session_id) / "graph_candidates.json"


def _chunk_count(session_id: UUID) -> int:
    return sum(len(artifact.chunks) for artifact in local.list_ingest_artifacts(session_id))


def _save_candidates(session_id: UUID, candidates: GraphExtractionResult) -> None:
    local.write_text_atomic(_candidates_path(session_id), candidates.model_dump_json(indent=2))


def _load_candidates(session_id: UUID) -> GraphExtractionResult:
    return GraphExtractionResult.model_validate_json(_candidates_path(session_id).read_text(encoding="utf-8"))


def _critic_report_path(session_id: UUID):
    return local.session_dir(session_id) / "graph_critic.json"


def _save_critic_report(session_id: UUID, report: GraphCriticReport) -> None:
    local.write_text_atomic(_critic_report_path(session_id), report.model_dump_json(indent=2))
