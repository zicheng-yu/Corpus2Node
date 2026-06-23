from __future__ import annotations

import uuid

from corpus2node.core.types import ConceptNode, EdgeType, EvidenceChunk, GraphEdge, SourceKind
from corpus2node.graph import build as B
from corpus2node.graph.schemas import ExtractedConcept, ExtractedRelation, GraphExtractionResult
from corpus2node.index.embeddings import HashingEmbeddings


def _concept(canonical: str, name: str, embedding: list[float]) -> ConceptNode:
    return ConceptNode(
        concept_id=f"concept:{canonical}",
        name=name,
        canonical_name=canonical,
        definition="d",
        summary="s",
        embedding=embedding,
    )


def _relates(a: ConceptNode, b: ConceptNode) -> GraphEdge:
    return GraphEdge(
        source=a.concept_id,
        target=b.concept_id,
        edge_type=EdgeType.relates_to,
        properties={"relation_type": "similar_to", "confidence": 0.9},
    )


# ── C: semantic merge ──────────────────────────────────────────────────────────

def test_semantic_merge_collapses_duplicates_only():
    dup1 = _concept("二叉搜索树", "二叉搜索树", [1.0, 0.0, 0.0])
    dup2 = _concept("二叉搜索树 bst", "二叉搜索树 BST", [1.0, 0.0, 0.0])  # same vec, substring-compatible
    other = _concept("傅里叶变换", "傅里叶变换", [0.0, 1.0, 0.0])

    merged, remap = B.semantic_merge([dup1, dup2, other], threshold=0.9)

    assert len(merged) == 2
    assert remap[dup1.concept_id] == remap[dup2.concept_id]
    assert remap[other.concept_id] == other.concept_id


def test_semantic_merge_collapses_same_display_name():
    # different canonical + orthogonal embeddings, but identical display name "字典"
    a = _concept("字典 dict", "字典", [1.0, 0.0])
    b = _concept("python 字典", "字典", [0.0, 1.0])
    merged, remap = B.semantic_merge([a, b], threshold=0.99)
    assert len(merged) == 1
    assert remap[a.concept_id] == remap[b.concept_id]


def test_semantic_merge_collapses_parenthetical_abbreviation():
    # "抽象数据类型" and "抽象数据类型（ADT）" should merge even with orthogonal vecs
    a = _concept("抽象数据类型", "抽象数据类型", [1.0, 0.0])
    b = _concept("抽象数据类型 adt", "抽象数据类型（ADT）", [0.0, 1.0])
    merged, remap = B.semantic_merge([a, b], threshold=0.99)
    assert len(merged) == 1
    assert remap[a.concept_id] == remap[b.concept_id]


def test_semantic_merge_keeps_close_but_incompatible_names_apart():
    a = _concept("梯度下降", "梯度下降", [1.0, 0.0])
    b = _concept("牛顿法", "牛顿法", [1.0, 0.0])  # identical vec but no name overlap
    merged, _ = B.semantic_merge([a, b], threshold=0.9)
    assert len(merged) == 2  # not merged — name guard


# ── A: communities ──────────────────────────────────────────────────────────────

def test_detect_communities_splits_two_cliques():
    nodes = [_concept(f"c{i}", f"c{i}", [float(i), 0.0]) for i in range(6)]
    edges = [
        _relates(nodes[0], nodes[1]), _relates(nodes[1], nodes[2]), _relates(nodes[0], nodes[2]),
        _relates(nodes[3], nodes[4]), _relates(nodes[4], nodes[5]), _relates(nodes[3], nodes[5]),
    ]
    clusters = B.detect_communities(nodes, edges)
    assert len(clusters) >= 2
    assigned = {cid for cluster in clusters for cid in cluster.concept_ids}
    assert assigned == {n.concept_id for n in nodes}


# ── centrality ──────────────────────────────────────────────────────────────────

def test_assign_metrics_in_unit_range_and_betweenness_peaks_in_middle():
    nodes = [_concept(f"c{i}", f"c{i}", [float(i), 0.0]) for i in range(4)]
    # path 0-1-2-3 -> node 1 and 2 are bridges
    edges = [_relates(nodes[0], nodes[1]), _relates(nodes[1], nodes[2]), _relates(nodes[2], nodes[3])]
    B.assign_metrics(nodes, edges)
    for node in nodes:
        keys = {"degree_centrality", "weighted_degree_centrality", "betweenness_centrality", "closeness_centrality"}
        assert keys <= set(node.graph_metrics)
        assert all(0.0 <= value <= 1.0 for value in node.graph_metrics.values())
    assert nodes[1].graph_metrics["betweenness_centrality"] > nodes[0].graph_metrics["betweenness_centrality"]


# ── end to end ──────────────────────────────────────────────────────────────────

def test_build_graph_artifact_end_to_end():
    session_id = uuid.uuid4()
    chunks = [
        EvidenceChunk(
            chunk_id=f"s-c{i}",
            source_id="s",
            source_type=SourceKind.pdf,
            text="二叉搜索树是一种树结构，用于高效查找。平衡树是二叉搜索树的改进。",
            summary="",
        )
        for i in range(3)
    ]
    candidates = GraphExtractionResult(
        concepts=[
            ExtractedConcept(name="二叉搜索树", canonical_name="二叉搜索树", definition="一种用于查找的树结构"),
            ExtractedConcept(name="平衡树", canonical_name="平衡树", definition="二叉搜索树的改进"),
            ExtractedConcept(name="树结构", canonical_name="树结构", definition="层次型数据结构"),
        ],
        relations=[
            ExtractedRelation(
                source_canonical_name="二叉搜索树", target_canonical_name="树结构",
                edge_type="RELATES_TO", relation_type="is_a", confidence=0.9,
            ),
            ExtractedRelation(
                source_canonical_name="平衡树", target_canonical_name="二叉搜索树",
                edge_type="RELATES_TO", relation_type="is_a", confidence=0.8,
            ),
        ],
    )

    graph = B.build_graph_artifact(session_id, chunks, candidates, embeddings=HashingEmbeddings(dims=128))

    assert graph.session_id == session_id
    assert len(graph.concepts) >= 2
    assert len(graph.edges) >= 2
    assert graph.topic_clusters  # at least one community
    assert all(concept.graph_metrics for concept in graph.concepts)
    assert any(concept.importance_score > 0 for concept in graph.concepts)
