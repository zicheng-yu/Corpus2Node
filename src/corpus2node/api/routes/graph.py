"""Read-only graph/search routes for the frontend (graph view, drawer, search panel).

Thin wrappers over storage + the in-memory retrieval layer, returning the donor's
frozen shapes (GraphArtifact / SubgraphResponse / SearchResponse) so the copied
frontend works unchanged.
"""
from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from corpus2node.core.types import (
    GraphArtifact,
    SearchChunkHit,
    SearchConceptHit,
    SearchResponse,
    SubgraphResponse,
)
from corpus2node.index import search
from corpus2node.index.embeddings import get_embeddings
from corpus2node.storage import local

router = APIRouter(prefix="/graph", tags=["graph"])


@router.get("/{session_id}")
def get_graph(session_id: UUID) -> GraphArtifact:
    try:
        return local.load_graph_artifact(session_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Graph not found. Run the workflow first.") from exc


@router.get("/{session_id}/subgraph")
def get_subgraph(session_id: UUID, concept_id: str, depth: int = 1, max_nodes: int = 20) -> SubgraphResponse:
    try:
        graph = local.load_graph_artifact(session_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Graph not found. Run the workflow first.") from exc
    return search.get_subgraph(graph, concept_id, depth=depth, max_nodes=max_nodes)


class SearchRequest(BaseModel):
    session_id: UUID
    query: str
    limit: int = 8


@router.post("/search")
def search_graph(request: SearchRequest) -> SearchResponse:
    try:
        graph = local.load_graph_artifact(request.session_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Graph not found. Run the workflow first.") from exc
    chunks = [chunk for artifact in local.list_ingest_artifacts(request.session_id) for chunk in artifact.chunks]
    embeddings = get_embeddings()

    concept_by_id = {concept.concept_id: concept for concept in graph.concepts}
    concept_hits: list[SearchConceptHit] = []
    for result in search.search_concepts(request.query, graph=graph, embeddings=embeddings, limit=request.limit):
        concept = concept_by_id.get(result.ref_id)
        if concept is None:
            continue
        concept_hits.append(
            SearchConceptHit(
                concept_id=concept.concept_id,
                name=concept.name,
                canonical_name=concept.canonical_name,
                score=result.score,
                source_count=concept.source_count,
                evidence_chunk_ids=[ref.chunk_id for ref in concept.evidence_refs],
            )
        )

    chunk_by_id = {chunk.chunk_id: chunk for chunk in chunks}
    chunk_hits: list[SearchChunkHit] = []
    for result in search.retrieve_chunks(request.query, chunks=chunks, embeddings=embeddings, limit=request.limit):
        chunk = chunk_by_id.get(result.ref_id)
        if chunk is None:
            continue
        chunk_hits.append(
            SearchChunkHit(
                chunk_id=chunk.chunk_id,
                source_id=chunk.source_id,
                source_type=chunk.source_type,
                score=result.score,
                text=chunk.text,
                page_start=chunk.page_start,
                page_end=chunk.page_end,
                time_start=chunk.time_start,
                time_end=chunk.time_end,
            )
        )

    return SearchResponse(
        session_id=request.session_id, query=request.query, concepts=concept_hits, chunks=chunk_hits
    )
