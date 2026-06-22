"""In-memory retrieval over the JSON graph artifact + chunk/concept embeddings.

Borrows the reference project's local/(global)/hybrid idea but stays artifact-based
(no Neo4j): cosine over stored vectors + bounded graph traversal. Returns a unified
RetrievalResult so the chat agent's tool outputs map straight to citations/subgraph.
"""
from __future__ import annotations

from collections import defaultdict

import numpy as np
from langchain_core.embeddings import Embeddings

from corpus2node.core.types import (
    EvidenceChunk,
    GraphArtifact,
    NodeType,
    RetrievalResult,
    SubgraphEdge,
    SubgraphNode,
    SubgraphResponse,
)


def retrieve_chunks(
    query: str, *, chunks: list[EvidenceChunk], embeddings: Embeddings, limit: int = 6
) -> list[RetrievalResult]:
    pool = [chunk for chunk in chunks if chunk.embedding]
    if not pool:
        return []
    ranked = _rank(embeddings.embed_query(query), [(chunk, chunk.embedding) for chunk in pool], limit)
    return [
        RetrievalResult(
            kind="chunk",
            ref_id=chunk.chunk_id,
            score=round(score, 4),
            title=(chunk.summary[:40] or "原文片段"),
            snippet=chunk.text[:200],
            locator=_locator(chunk),
            source_id=chunk.source_id,
            source_type=chunk.source_type,
        )
        for chunk, score in ranked
    ]


def search_concepts(
    query: str, *, graph: GraphArtifact, embeddings: Embeddings, limit: int = 6
) -> list[RetrievalResult]:
    pool = [concept for concept in graph.concepts if concept.embedding]
    if not pool:
        return []
    ranked = _rank(embeddings.embed_query(query), [(concept, concept.embedding) for concept in pool], limit)
    return [
        RetrievalResult(
            kind="concept",
            ref_id=concept.concept_id,
            score=round(score, 4),
            title=concept.name,
            snippet=concept.definition or concept.summary,
            locator="概念",
            concept_ids=[concept.concept_id],
            metadata={"importance": concept.importance_score},
        )
        for concept, score in ranked
    ]


def local_search(
    query: str, *, graph: GraphArtifact, chunks: list[EvidenceChunk], embeddings: Embeddings, limit: int = 6
) -> list[RetrievalResult]:
    """Chunk + concept retrieval merged, deduped, sorted by score."""
    results = retrieve_chunks(query, chunks=chunks, embeddings=embeddings, limit=limit) + search_concepts(
        query, graph=graph, embeddings=embeddings, limit=limit
    )
    return dedup(sorted(results, key=lambda result: result.score, reverse=True))


def dedup(results: list[RetrievalResult]) -> list[RetrievalResult]:
    seen: set[tuple[str, str]] = set()
    out: list[RetrievalResult] = []
    for result in results:
        key = (result.kind, result.ref_id)
        if key in seen:
            continue
        seen.add(key)
        out.append(result)
    return out


def get_subgraph(
    graph: GraphArtifact, center_concept_id: str, *, depth: int = 1, max_nodes: int = 20
) -> SubgraphResponse:
    by_id = {concept.concept_id: concept for concept in graph.concepts}
    if center_concept_id not in by_id:
        return SubgraphResponse(session_id=graph.session_id, center_concept_id=center_concept_id, nodes=[], edges=[])

    adjacency: dict[str, set[str]] = defaultdict(set)
    for edge in graph.edges:
        adjacency[edge.source].add(edge.target)
        adjacency[edge.target].add(edge.source)

    visited = {center_concept_id}
    frontier = [center_concept_id]
    for _ in range(max(0, depth)):
        nxt: list[str] = []
        for node in frontier:
            for neighbor in adjacency[node]:
                if neighbor not in visited and len(visited) < max_nodes:
                    visited.add(neighbor)
                    nxt.append(neighbor)
        frontier = nxt
        if len(visited) >= max_nodes:
            break

    nodes = [
        SubgraphNode(
            id=cid,
            label=by_id[cid].name,
            node_type=NodeType.concept,
            metadata={"importance": by_id[cid].importance_score},
        )
        for cid in visited
        if cid in by_id
    ]
    edges = [
        SubgraphEdge(source=edge.source, target=edge.target, edge_type=edge.edge_type, properties=edge.properties)
        for edge in graph.edges
        if edge.source in visited and edge.target in visited
    ]
    return SubgraphResponse(session_id=graph.session_id, center_concept_id=center_concept_id, nodes=nodes, edges=edges)


def _rank(query_vec, items, k):
    if not items or k <= 0:
        return []
    matrix = np.asarray([vector for _, vector in items], dtype=float)
    norms = np.linalg.norm(matrix, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    unit = matrix / norms
    query = np.asarray(query_vec, dtype=float)
    query_norm = float(np.linalg.norm(query)) or 1.0
    scores = unit @ (query / query_norm)
    order = np.argsort(-scores)[:k]
    return [(items[i][0], float(scores[i])) for i in order]


def _locator(chunk: EvidenceChunk) -> str:
    if chunk.page_start is not None:
        return f"第 {chunk.page_start} 页"
    if chunk.time_start is not None:
        return f"{int(chunk.time_start // 60):02d}:{int(chunk.time_start % 60):02d}"
    return chunk.chunk_id
