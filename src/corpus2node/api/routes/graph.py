"""Read-only graph/search routes for the frontend (graph view, drawer, search panel).

Thin wrappers over storage + the in-memory retrieval layer, returning the donor's
frozen shapes (GraphArtifact / SubgraphResponse / SearchResponse) so the copied
frontend works unchanged.
"""
from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from corpus2node.accounts.database import get_db
from corpus2node.accounts.dependencies import optional_principal, require_resource_access
from corpus2node.accounts.models import Resource
from corpus2node.core.types import (
    GraphArtifactView,
    SearchChunkHit,
    SearchConceptHit,
    SearchResponse,
    SubgraphResponse,
)
from corpus2node.index import search
from corpus2node.index.embeddings import (
    EmbeddingProvenanceError,
    ensure_embedding_compatible,
    get_embeddings,
)
from corpus2node.storage import local

router = APIRouter(prefix="/graph", tags=["graph"])

COURSE_GRAPH_LECTURE_PREFIX = "[总图谱] "


class GlobalConceptHit(BaseModel):
    session_id: UUID
    course_title: str
    lecture_title: str
    concept_id: str
    name: str
    canonical_name: str
    importance_score: float


@router.get("/concepts")
async def search_concepts_global(
    q: str,
    request: Request,
    limit: int = 20,
    db: AsyncSession = Depends(get_db),
) -> list[GlobalConceptHit]:
    """Substring-search concepts across every built graph (for the global search bars)."""
    needle = q.strip().lower()
    if not needle:
        return []
    hits: list[GlobalConceptHit] = []
    session_ids = local.list_session_ids()
    principal = optional_principal(request)
    if principal is not None:
        keys = (
            await db.scalars(
                select(Resource.resource_key).where(
                    Resource.organization_id == principal.organization_id,
                    Resource.resource_type == "session",
                    Resource.status == "active",
                )
            )
        ).all()
        session_ids = [UUID(value) for value in keys]
    for session_id in session_ids:
        try:
            session = local.load_session(session_id)
            graph = local.load_graph_artifact(session_id)
        except (FileNotFoundError, ValueError):
            continue
        if session.lecture_title.startswith(COURSE_GRAPH_LECTURE_PREFIX):
            continue  # skip virtual course-graph sessions
        for concept in graph.concepts:
            haystack = [concept.name, concept.canonical_name, *concept.aliases]
            if any(needle in (value or "").lower() for value in haystack):
                hits.append(
                    GlobalConceptHit(
                        session_id=session_id,
                        course_title=session.course_title,
                        lecture_title=session.lecture_title,
                        concept_id=concept.concept_id,
                        name=concept.name,
                        canonical_name=concept.canonical_name,
                        importance_score=concept.importance_score,
                    )
                )
    hits.sort(key=lambda hit: hit.importance_score, reverse=True)
    return hits[:limit]


@router.get("/{session_id}")
async def get_graph(
    session_id: UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> GraphArtifactView:
    await require_resource_access(request, db, "session", str(session_id))
    try:
        return GraphArtifactView.from_artifact(local.load_graph_artifact(session_id))
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Graph not found. Run the workflow first.") from exc


@router.get("/{session_id}/subgraph")
async def get_subgraph(
    session_id: UUID,
    concept_id: str,
    request: Request,
    depth: int = 1,
    max_nodes: int = 20,
    db: AsyncSession = Depends(get_db),
) -> SubgraphResponse:
    await require_resource_access(request, db, "session", str(session_id))
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
async def search_graph(
    payload: SearchRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> SearchResponse:
    await require_resource_access(request, db, "session", str(payload.session_id))
    try:
        graph = local.load_graph_artifact(payload.session_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Graph not found. Run the workflow first.") from exc
    chunks = [chunk for artifact in local.list_ingest_artifacts(payload.session_id) for chunk in artifact.chunks]
    embeddings = get_embeddings()
    try:
        ensure_embedding_compatible(graph, embeddings)
    except EmbeddingProvenanceError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    concept_by_id = {concept.concept_id: concept for concept in graph.concepts}
    concept_hits: list[SearchConceptHit] = []
    for result in search.search_concepts(payload.query, graph=graph, embeddings=embeddings, limit=payload.limit):
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
    for result in search.retrieve_chunks(payload.query, chunks=chunks, embeddings=embeddings, limit=payload.limit):
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
        session_id=payload.session_id, query=payload.query, concepts=concept_hits, chunks=chunk_hits
    )
