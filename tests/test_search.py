from __future__ import annotations

import uuid

from corpus2node.core.types import ConceptNode, EdgeType, EvidenceChunk, GraphArtifact, GraphEdge, SourceKind
from corpus2node.index import search
from corpus2node.index.embeddings import HashingEmbeddings

# NOTE: HashingEmbeddings tokenizes CJK as whole runs, so test text separates
# Chinese words with spaces to give meaningful token-overlap cosine.
EMB = HashingEmbeddings(dims=256)


def _chunk(i: int, text: str) -> EvidenceChunk:
    return EvidenceChunk(
        chunk_id=f"s-c{i}", source_id="s", source_type=SourceKind.pdf,
        text=text, summary=text[:16], embedding=EMB.embed_query(text),
    )


def _concept(cid: str, name: str, definition: str) -> ConceptNode:
    return ConceptNode(
        concept_id=f"concept:{cid}", name=name, canonical_name=cid,
        definition=definition, summary=definition, embedding=EMB.embed_query(f"{name} | {definition}"),
    )


def _graph(concepts, edges) -> GraphArtifact:
    return GraphArtifact(session_id=uuid.uuid4(), concepts=concepts, topic_clusters=[], edges=edges)


def test_retrieve_chunks_ranks_relevant_first():
    chunks = [_chunk(0, "二叉搜索树 用于 高效 查找"), _chunk(1, "傅里叶变换 用于 频域 分析")]
    results = search.retrieve_chunks("二叉搜索树 查找", chunks=chunks, embeddings=EMB, limit=2)
    assert results and results[0].ref_id == "s-c0"
    assert results[0].kind == "chunk"


def test_search_concepts_ranks_relevant_first():
    concepts = [_concept("二叉搜索树", "二叉搜索树", "用于 查找 的 树"), _concept("傅里叶变换", "傅里叶变换", "频域 分析")]
    results = search.search_concepts("查找 树", graph=_graph(concepts, []), embeddings=EMB, limit=2)
    ids = [r.ref_id for r in results]
    assert ids.index("concept:二叉搜索树") < ids.index("concept:傅里叶变换")


def test_local_search_dedups_and_mixes_kinds():
    chunks = [_chunk(0, "二叉搜索树 查找")]
    concepts = [_concept("二叉搜索树", "二叉搜索树", "查找 树")]
    results = search.local_search("二叉搜索树", graph=_graph(concepts, []), chunks=chunks, embeddings=EMB, limit=5)
    keys = [(r.kind, r.ref_id) for r in results]
    assert len(keys) == len(set(keys))
    assert any(r.kind == "chunk" for r in results) and any(r.kind == "concept" for r in results)


def test_get_subgraph_depth_and_node_cap():
    concepts = [_concept(f"c{i}", f"c{i}", f"d{i}") for i in range(5)]
    edges = [
        GraphEdge(source="concept:c0", target=f"concept:c{i}", edge_type=EdgeType.relates_to, properties={})
        for i in range(1, 5)
    ]
    graph = _graph(concepts, edges)

    full = search.get_subgraph(graph, "concept:c0", depth=1, max_nodes=20)
    assert {n.id for n in full.nodes} == {f"concept:c{i}" for i in range(5)}

    capped = search.get_subgraph(graph, "concept:c0", depth=1, max_nodes=3)
    assert len(capped.nodes) <= 3

    missing = search.get_subgraph(graph, "concept:nope", depth=1)
    assert missing.nodes == []


def test_get_subgraph_resolves_center_by_name():
    concepts = [_concept("二叉搜索树", "二叉搜索树", "树"), _concept("树结构", "树结构", "层次")]
    edges = [GraphEdge(source="concept:二叉搜索树", target="concept:树结构", edge_type=EdgeType.relates_to, properties={})]
    # pass the NAME, not the id — should still resolve
    sg = search.get_subgraph(_graph(concepts, edges), "二叉搜索树", depth=1, max_nodes=20)
    assert sg.nodes and sg.center_concept_id == "concept:二叉搜索树"
