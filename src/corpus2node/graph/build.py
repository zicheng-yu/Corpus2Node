"""Deterministic graph build (rewritten to fix the donor's real defects).

- C: semantic concept merge (embedding cosine) collapses cross-batch duplicates
     the donor's string-only canonical merge left split.
- A: communities via networkx Louvain (donor used connected components, which
     collapse a connected lecture into one useless "cluster").
- centrality via networkx (donor hand-rolled Brandes — hard to verify).
- co-occurrence edges so single-lecture graphs aren't edge-sparse.
The tuned cleaning (is_junk_concept) and the LLM-relation mapping are kept.
"""
from __future__ import annotations

import itertools
import logging
from collections import Counter, defaultdict
from uuid import UUID

import networkx as nx
import numpy as np
from langchain_core.embeddings import Embeddings

from corpus2node.core.text import canonicalize_term, summarize_text
from corpus2node.core.types import (
    ConceptNode,
    EdgeType,
    EvidenceChunk,
    EvidenceRef,
    GraphArtifact,
    GraphEdge,
    TopicClusterNode,
)
from corpus2node.graph.clean import is_junk_concept
from corpus2node.graph.schemas import GraphExtractionResult

logger = logging.getLogger(__name__)

SEMANTIC_MERGE_THRESHOLD = 0.90
COOCCUR_CLOSE_THRESHOLD = 0.48


def build_graph_artifact(
    session_id: UUID,
    chunks: list[EvidenceChunk],
    candidates: GraphExtractionResult,
    *,
    embeddings: Embeddings,
) -> GraphArtifact:
    """Turn extraction candidates + chunks into a finished, clustered GraphArtifact."""
    concepts = concepts_from_candidates(chunks, candidates)
    concepts = [c for c in concepts if not is_junk_concept(c.canonical_name)]
    if not concepts:
        raise ValueError("No valid concepts remain after cleaning.")

    _embed_concepts(concepts, embeddings)
    concepts, _remap = semantic_merge(concepts, threshold=SEMANTIC_MERGE_THRESHOLD)

    edges, edge_keys = build_llm_edges(concepts, candidates)
    edges.extend(build_cooccurrence_edges(chunks, concepts, existing_keys=edge_keys))

    assign_metrics(concepts, edges)
    compute_importance(concepts)
    attach_evidence(concepts, chunks)
    clusters = detect_communities(concepts, edges)

    return GraphArtifact(session_id=session_id, concepts=concepts, topic_clusters=clusters, edges=edges)


# ── concepts ──────────────────────────────────────────────────────────────────

def concepts_from_candidates(
    chunks: list[EvidenceChunk], candidates: GraphExtractionResult
) -> list[ConceptNode]:
    concepts: list[ConceptNode] = []
    seen: set[str] = set()
    for candidate in candidates.concepts:
        canonical = canonicalize_term(candidate.canonical_name or candidate.name)
        concept_id = f"concept:{canonical}"
        if not canonical or concept_id in seen:
            continue
        seen.add(concept_id)
        aliases = sorted({a for a in [candidate.name, candidate.canonical_name, *candidate.aliases] if a.strip()})
        definition = candidate.definition.strip() or summarize_text(
            candidate.summary or candidate.name, max_sentences=1, max_chars=150
        )
        concepts.append(
            ConceptNode(
                concept_id=concept_id,
                name=candidate.name or canonical,
                canonical_name=canonical,
                aliases=aliases[:10],
                definition=definition,
                summary=candidate.summary.strip() or definition,
                key_points=candidate.key_points[:4],
                tags=candidate.tags[:5],
                prerequisites=candidate.prerequisites[:4],
                applications=candidate.applications[:4],
                embedding=[],
                importance_score=0.0,
                source_count=_matching_source_count(chunks, aliases or [candidate.name]),
            )
        )
    return concepts


def _matching_source_count(chunks: list[EvidenceChunk], terms: list[str]) -> int:
    lowered = [term.lower() for term in terms if term]
    if not lowered:
        return 0
    return len({chunk.source_id for chunk in chunks if any(term in chunk.text.lower() for term in lowered)})


def _concept_text(concept: ConceptNode) -> str:
    parts = [concept.name, concept.definition, concept.summary, " ; ".join(concept.key_points), " ; ".join(concept.tags)]
    return " | ".join(part for part in parts if part)


def _embed_concepts(concepts: list[ConceptNode], embeddings: Embeddings) -> None:
    if not concepts:
        return
    vectors = embeddings.embed_documents([_concept_text(c) for c in concepts])
    if len(vectors) != len(concepts):
        raise RuntimeError("Embedding provider returned an unexpected number of vectors.")
    for concept, vector in zip(concepts, vectors):
        concept.embedding = list(vector)


# ── C: semantic merge ───────────────────────────────────────────────────────

def semantic_merge(
    concepts: list[ConceptNode], *, threshold: float = SEMANTIC_MERGE_THRESHOLD
) -> tuple[list[ConceptNode], dict[str, str]]:
    """Merge near-duplicate concepts by embedding cosine + name compatibility.

    Returns (merged_concepts, remap) where remap maps every original concept_id
    to the surviving representative's concept_id.
    """
    identity = {c.concept_id: c.concept_id for c in concepts}
    n = len(concepts)
    if n < 2:
        return concepts, identity
    dims = len(concepts[0].embedding)
    if dims == 0 or any(len(c.embedding) != dims for c in concepts):
        return concepts, identity  # can't compare — leave untouched

    matrix = np.asarray([c.embedding for c in concepts], dtype=float)
    norms = np.linalg.norm(matrix, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    sim = (matrix / norms) @ (matrix / norms).T

    parent = list(range(n))

    def find(x: int) -> int:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a: int, b: int) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[max(ra, rb)] = min(ra, rb)

    for i in range(n):
        for j in range(i + 1, n):
            if sim[i, j] >= threshold and _name_compatible(concepts[i], concepts[j]):
                union(i, j)

    groups: dict[int, list[int]] = defaultdict(list)
    for i in range(n):
        groups[find(i)].append(i)

    merged: list[ConceptNode] = []
    remap: dict[str, str] = {}
    for members_idx in groups.values():
        members = [concepts[i] for i in members_idx]
        rep = max(members, key=lambda c: (c.source_count, len(c.definition), len(c.name)))
        rep.aliases = sorted({a for m in members for a in [m.name, m.canonical_name, *m.aliases] if a})[:12]
        rep.definition = max((m.definition for m in members), key=len, default=rep.definition)
        rep.summary = max((m.summary for m in members), key=len, default=rep.summary)
        rep.source_count = max(m.source_count for m in members)
        merged.append(rep)
        for m in members:
            remap[m.concept_id] = rep.concept_id

    if len(merged) < n:
        logger.info("semantic merge collapsed %d concepts into %d", n, len(merged))
    return merged, remap


def _name_compatible(a: ConceptNode, b: ConceptNode) -> bool:
    """Guard against merging embedding-close but genuinely different concepts."""
    ca, cb = a.canonical_name, b.canonical_name
    if ca and cb and (ca in cb or cb in ca):
        return True
    if set(ca.split()) & set(cb.split()):
        return True
    return bool({x.lower() for x in a.aliases} & {x.lower() for x in b.aliases})


# ── edges ─────────────────────────────────────────────────────────────────────

EdgeKey = tuple[str, str, str, str | None]


def build_llm_edges(
    concepts: list[ConceptNode], candidates: GraphExtractionResult
) -> tuple[list[GraphEdge], set[EdgeKey]]:
    by_canonical: dict[str, ConceptNode] = {}
    for concept in concepts:
        for term in {concept.canonical_name, *(canonicalize_term(a) for a in concept.aliases)}:
            if term:
                by_canonical.setdefault(term, concept)

    edges: list[GraphEdge] = []
    keys: set[EdgeKey] = set()
    for relation in candidates.relations:
        source = by_canonical.get(canonicalize_term(relation.source_canonical_name))
        target = by_canonical.get(canonicalize_term(relation.target_canonical_name))
        if source is None or target is None or source.concept_id == target.concept_id:
            continue
        try:
            edge_type = EdgeType(relation.edge_type)
        except ValueError:
            continue
        relation_type = relation.relation_type if edge_type == EdgeType.relates_to else None
        key: EdgeKey = (source.concept_id, target.concept_id, edge_type.value, relation_type)
        if key in keys:
            continue
        keys.add(key)
        properties: dict[str, object] = {"confidence": round(max(relation.confidence, 0.55), 2)}
        if relation_type:
            properties["relation_type"] = relation_type
        edges.append(GraphEdge(source=source.concept_id, target=target.concept_id, edge_type=edge_type, properties=properties))
    return edges, keys


def build_cooccurrence_edges(
    chunks: list[EvidenceChunk], concepts: list[ConceptNode], *, existing_keys: set[EdgeKey]
) -> list[GraphEdge]:
    terms = {
        c.concept_id: {t.lower() for t in {c.name, c.canonical_name, *c.aliases} if t}
        for c in concepts
    }
    by_id = {c.concept_id: c for c in concepts}
    counts: Counter[tuple[str, str]] = Counter()
    for chunk in chunks:
        lowered = chunk.text.lower()
        mentioned = [cid for cid, cterms in terms.items() if any(term in lowered for term in cterms)]
        for left, right in itertools.combinations(sorted(mentioned), 2):
            counts[(left, right)] += 1

    edges: list[GraphEdge] = []
    for (left, right), count in counts.items():
        close = _cosine(by_id[left].embedding, by_id[right].embedding) > COOCCUR_CLOSE_THRESHOLD
        if count < 2 and not close:
            continue
        key: EdgeKey = (left, right, EdgeType.co_occurs_with.value, None)
        if key in existing_keys:
            continue
        existing_keys.add(key)
        edges.append(
            GraphEdge(
                source=left,
                target=right,
                edge_type=EdgeType.co_occurs_with,
                properties={"cooccur_count": count, "normalized_weight": round(min(1.0, 0.2 * count), 3)},
            )
        )
    return edges


def _cosine(a: list[float], b: list[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    va, vb = np.asarray(a, dtype=float), np.asarray(b, dtype=float)
    na, nb = float(np.linalg.norm(va)), float(np.linalg.norm(vb))
    if na == 0 or nb == 0:
        return 0.0
    return float(va @ vb / (na * nb))


# ── centrality + communities (networkx) ────────────────────────────────────────

def _edge_weight(edge: GraphEdge) -> float:
    confidence = float(edge.properties.get("confidence", 0.0))
    if edge.edge_type == EdgeType.relates_to:
        return 1.0 + confidence
    if edge.edge_type == EdgeType.co_occurs_with:
        return 0.5 + float(edge.properties.get("normalized_weight", 0.0))
    if edge.edge_type == EdgeType.contains:
        return 0.9 + confidence
    if edge.edge_type == EdgeType.mentions:
        return 0.4 + confidence
    return 1.0


def _nx_graph(concepts: list[ConceptNode], edges: list[GraphEdge]) -> nx.Graph:
    ids = {c.concept_id for c in concepts}
    graph = nx.Graph()
    graph.add_nodes_from(ids)
    for edge in edges:
        if edge.source not in ids or edge.target not in ids:
            continue
        weight = _edge_weight(edge)
        if graph.has_edge(edge.source, edge.target):
            graph[edge.source][edge.target]["weight"] += weight
        else:
            graph.add_edge(edge.source, edge.target, weight=weight)
    return graph


def assign_metrics(concepts: list[ConceptNode], edges: list[GraphEdge]) -> None:
    graph = _nx_graph(concepts, edges)
    n = graph.number_of_nodes()
    if n == 0:
        return

    degree = nx.degree_centrality(graph)
    closeness = nx.closeness_centrality(graph)
    # Topology-based betweenness (weights here are affinity, not distance); sample on large graphs.
    if graph.number_of_edges() == 0:
        betweenness = {node: 0.0 for node in graph}
    elif n > 200:
        betweenness = nx.betweenness_centrality(graph, k=min(n, 128), normalized=True, seed=42)
    else:
        betweenness = nx.betweenness_centrality(graph, normalized=True)

    weighted_degree = {node: 0.0 for node in graph}
    for u, v, data in graph.edges(data=True):
        weighted_degree[u] += data["weight"]
        weighted_degree[v] += data["weight"]
    max_weighted = max(weighted_degree.values(), default=0.0) or 1.0

    for concept in concepts:
        cid = concept.concept_id
        concept.graph_metrics = {
            "degree_centrality": round(degree.get(cid, 0.0), 4),
            "weighted_degree_centrality": round(weighted_degree.get(cid, 0.0) / max_weighted, 4),
            "betweenness_centrality": round(betweenness.get(cid, 0.0), 4),
            "closeness_centrality": round(closeness.get(cid, 0.0), 4),
        }


def compute_importance(concepts: list[ConceptNode]) -> None:
    max_source = max((c.source_count for c in concepts), default=0) or 1
    for concept in concepts:
        metrics = concept.graph_metrics
        structural = (
            0.40 * metrics.get("weighted_degree_centrality", 0.0)
            + 0.25 * metrics.get("betweenness_centrality", 0.0)
            + 0.15 * metrics.get("closeness_centrality", 0.0)
            + 0.10 * metrics.get("degree_centrality", 0.0)
        )
        coverage = concept.source_count / max_source
        concept.importance_score = round(min(1.0, 0.8 * structural + 0.2 * coverage), 4)


def chunk_locator(chunk: EvidenceChunk) -> str:
    """A human-citable locator for a chunk (page / timestamp / id)."""
    if chunk.page_start is not None:
        return f"第 {chunk.page_start} 页" if chunk.page_end in (None, chunk.page_start) else f"第 {chunk.page_start}-{chunk.page_end} 页"
    if chunk.time_start is not None:
        return f"{int(chunk.time_start // 60):02d}:{int(chunk.time_start % 60):02d}"
    return chunk.chunk_id


def attach_evidence(concepts: list[ConceptNode], chunks: list[EvidenceChunk], *, max_refs: int = 5) -> None:
    """Link each concept to the source chunks that mention it (for citations)."""
    terms_by_concept = {
        c.concept_id: {t.lower() for t in {c.name, c.canonical_name, *c.aliases} if t}
        for c in concepts
    }
    for concept in concepts:
        terms = terms_by_concept[concept.concept_id]
        refs: list[EvidenceRef] = []
        for chunk in chunks:
            lowered = chunk.text.lower()
            if any(term in lowered for term in terms):
                refs.append(
                    EvidenceRef(
                        chunk_id=chunk.chunk_id,
                        source_id=chunk.source_id,
                        source_type=chunk.source_type,
                        locator=chunk_locator(chunk),
                        snippet=chunk.text[:160],
                        score=1.0,
                    )
                )
                if len(refs) >= max_refs:
                    break
        concept.evidence_refs = refs


def detect_communities(concepts: list[ConceptNode], edges: list[GraphEdge]) -> list[TopicClusterNode]:
    graph = _nx_graph(concepts, edges)
    if graph.number_of_nodes() == 0:
        return []
    if graph.number_of_edges() == 0:
        communities: list[set[str]] = [{node} for node in graph.nodes]
    else:
        try:
            from networkx.algorithms.community import louvain_communities

            communities = louvain_communities(graph, weight="weight", seed=42)
        except Exception:  # pragma: no cover - fallback if louvain unavailable
            from networkx.algorithms.community import greedy_modularity_communities

            communities = [set(group) for group in greedy_modularity_communities(graph, weight="weight")]

    by_id = {c.concept_id: c for c in concepts}
    clusters: list[TopicClusterNode] = []
    for index, community in enumerate(sorted(communities, key=len, reverse=True), start=1):
        members = sorted(
            (by_id[cid] for cid in community if cid in by_id),
            key=lambda c: c.importance_score,
            reverse=True,
        )
        if not members:
            continue
        top_names = [m.name for m in members[:3]]
        clusters.append(
            TopicClusterNode(
                cluster_id=f"cluster:{index}",
                title=" / ".join(top_names),
                summary=f"围绕 {', '.join(top_names)} 的知识点簇。",
                concept_ids=[m.concept_id for m in members],
            )
        )
    return clusters
