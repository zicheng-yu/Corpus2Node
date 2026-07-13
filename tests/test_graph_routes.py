from __future__ import annotations

import uuid

from fastapi.testclient import TestClient

from corpus2node.api.app import app
from corpus2node.config import settings
from corpus2node.core.types import EvidenceChunk, IngestArtifact, SourceKind
from corpus2node.graph.build import build_graph_artifact
from corpus2node.graph.schemas import ExtractedConcept, ExtractedRelation, GraphExtractionResult
from corpus2node.index.embeddings import embedding_signature, get_embeddings
from corpus2node.storage import local

client = TestClient(app)


def _seed_graph() -> uuid.UUID:
    """Build + persist a small graph and its ingest chunks for a fresh session.

    Seeds embeddings with the SAME provider the routes use (get_embeddings), so
    stored-vector dimensions match the query vectors the route generates.
    """
    monkeypatch_provider()
    emb = get_embeddings()
    session_id = uuid.uuid4()
    chunks = [
        EvidenceChunk(
            chunk_id=f"s-c{i}", source_id="s", source_type=SourceKind.pdf,
            text="二叉搜索树 是 一种 树结构 ，用于 高效 查找。平衡树 是 二叉搜索树 的 改进。",
            summary="二叉搜索树", embedding=emb.embed_query("二叉搜索树 树结构 查找"),
        )
        for i in range(2)
    ]
    local.save_ingest_artifact(
        IngestArtifact(session_id=session_id, source_id=uuid.uuid4(), source_kind=SourceKind.pdf, chunks=chunks)
    )
    candidates = GraphExtractionResult(
        concepts=[
            ExtractedConcept(name="二叉搜索树", canonical_name="二叉搜索树", definition="用于查找的树结构"),
            ExtractedConcept(name="树结构", canonical_name="树结构", definition="层次型数据结构"),
        ],
        relations=[
            ExtractedRelation(
                source_canonical_name="二叉搜索树", target_canonical_name="树结构",
                edge_type="RELATES_TO", relation_type="is_a", confidence=0.9,
            )
        ],
    )
    graph = build_graph_artifact(session_id, chunks, candidates, embeddings=emb)
    graph.provenance.embedding_signature = embedding_signature(emb)
    local.save_graph_artifact(graph)
    return session_id


def monkeypatch_provider() -> None:
    # search routes call get_embeddings(); force the dependency-free hashing provider
    settings.embed_provider = "hashing"


def test_get_graph_returns_artifact():
    session_id = _seed_graph()
    res = client.get(f"/graph/{session_id}")
    assert res.status_code == 200
    body = res.json()
    assert body["concepts"] and "concept_id" in body["concepts"][0]
    assert "embedding" not in body["concepts"][0]
    assert body["concepts"][0]["source_count"] > 0
    assert body["concepts"][0]["evidence_refs"]
    assert body["edges"]

    persisted = local.load_graph_artifact(session_id)
    assert persisted.concepts[0].embedding
    assert persisted.concepts[0].evidence_refs


def test_get_graph_missing_is_404():
    res = client.get(f"/graph/{uuid.uuid4()}")
    assert res.status_code == 404


def test_subgraph_route():
    session_id = _seed_graph()
    concept_id = client.get(f"/graph/{session_id}").json()["concepts"][0]["concept_id"]
    res = client.get(f"/graph/{session_id}/subgraph", params={"concept_id": concept_id, "depth": 1})
    assert res.status_code == 200
    body = res.json()
    assert body["center_concept_id"] == concept_id
    assert body["nodes"]


def test_search_route_returns_search_response_shape():
    session_id = _seed_graph()
    res = client.post("/graph/search", json={"session_id": str(session_id), "query": "二叉搜索树 查找", "limit": 5})
    assert res.status_code == 200
    body = res.json()
    assert set(body) >= {"session_id", "query", "concepts", "chunks"}
    assert body["concepts"] and "canonical_name" in body["concepts"][0]
    assert body["chunks"] and "text" in body["chunks"][0]


def test_global_concept_search_route():
    from corpus2node.core.types import CourseSession

    session_id = _seed_graph()
    local.save_session(CourseSession(session_id=session_id, course_title="数据结构", lecture_title="树与查找"))

    res = client.get("/graph/concepts", params={"q": "树", "limit": 10})
    assert res.status_code == 200
    hits = res.json()
    assert hits and any("树" in hit["name"] for hit in hits)
    assert hits[0]["session_id"] == str(session_id)
    assert {"course_title", "lecture_title", "concept_id", "name", "importance_score"} <= set(hits[0])
    # blank query → no hits
    assert client.get("/graph/concepts", params={"q": "   "}).json() == []
    # a non-matching needle → no hits
    assert client.get("/graph/concepts", params={"q": "量子色动力学"}).json() == []


def test_delete_session_and_chat():
    session_id = _seed_graph()
    # create a real session file so delete has something to load
    from corpus2node.core.types import CourseSession

    local.save_session(CourseSession(session_id=session_id, course_title="c", lecture_title="l"))
    assert client.delete(f"/chat/{session_id}").status_code == 200
    assert client.delete(f"/sessions/{session_id}").status_code == 200
    assert client.delete(f"/sessions/{uuid.uuid4()}").status_code == 404
