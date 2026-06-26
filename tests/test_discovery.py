from __future__ import annotations

import asyncio
import re
import uuid

from fastapi.testclient import TestClient

from corpus2node.api.app import app
from corpus2node.core.types import (
    ConceptNode,
    CourseSession,
    DiscoveryMode,
    DiscoveryRequest,
    EvidenceChunk,
    GraphArtifact,
    IngestArtifact,
    SessionStatus,
    SourceKind,
)
from corpus2node.discovery.engine import (
    RELATION_TYPES,
    JudgedFinding,
    JudgeReport,
    run_discovery,
)
from corpus2node.storage import local

client = TestClient(app)


def _seed_session(
    *,
    course_title: str,
    lecture_title: str,
    concepts: list[tuple[str, list[float], str]],
    virtual: bool = False,
) -> uuid.UUID:
    session = CourseSession(
        course_title=course_title,
        lecture_title=f"{local.COURSE_GRAPH_LECTURE_PREFIX}{lecture_title}" if virtual else lecture_title,
        status=SessionStatus.graph_ready,
    )
    local.save_session(session)
    nodes: list[ConceptNode] = []
    chunks: list[EvidenceChunk] = []
    source_id = uuid.uuid4()
    for index, (name, embedding, summary) in enumerate(concepts):
        concept_id = f"concept:{name}"
        nodes.append(
            ConceptNode(
                concept_id=concept_id,
                name=name,
                canonical_name=name,
                summary=summary,
                definition=summary,
                tags=["发现"],
                applications=["跨资料串联"],
                embedding=embedding,
                importance_score=0.8 - index * 0.1,
            )
        )
        chunks.append(
            EvidenceChunk(
                chunk_id=f"{session.session_id}-chunk-{index}",
                source_id=str(source_id),
                source_type=SourceKind.document,
                text=f"{name}：{summary}",
                summary=summary,
                embedding=embedding,
            )
        )
    local.save_graph_artifact(GraphArtifact(session_id=session.session_id, concepts=nodes, edges=[]))
    local.save_ingest_artifact(
        IngestArtifact(session_id=session.session_id, source_id=source_id, source_kind=SourceKind.document, chunks=chunks)
    )
    return session.session_id


def test_run_discovery_returns_algorithmic_report_with_bridge_graph():
    left = _seed_session(
        course_title="算法",
        lecture_title="图搜索",
        concepts=[("启发式搜索", [1.0, 0.0, 0.0], "用估价函数引导搜索路径。")],
    )
    right = _seed_session(
        course_title="机器学习",
        lecture_title="推荐系统",
        concepts=[("候选召回", [0.9, 0.1, 0.0], "用粗排策略先召回可能相关的候选。")],
    )

    report = asyncio.run(run_discovery(DiscoveryRequest(session_ids=[left, right]), judge=None))

    assert report.mode == DiscoveryMode.selected
    assert report.session_ids == [left, right]
    assert report.findings
    finding = report.findings[0]
    assert len(finding.participants) == 2
    assert len({item.session_id for item in finding.participants}) == 2
    assert finding.evidence and all(e.snippet for e in finding.evidence)
    assert report.bridge_graph.nodes
    assert report.bridge_graph.edges


def test_run_discovery_uses_injected_ai_judge_for_non_name_based_crossing():
    left = _seed_session(
        course_title="系统",
        lecture_title="调度",
        concepts=[("背压控制", [0.0, 1.0, 0.0], "通过反馈限制上游速率，避免队列无限增长。")],
    )
    right = _seed_session(
        course_title="学习",
        lecture_title="复习计划",
        concepts=[("间隔复习", [0.0, 0.2, 0.8], "根据遗忘曲线调节复习频率。")],
    )

    async def fake_judge(prompt: str) -> JudgeReport:
        candidate_id = re.search(r"候选 (cand-\d+)", prompt).group(1)  # type: ignore[union-attr]
        return JudgeReport(
            findings=[
                JudgedFinding(
                    candidate_id=candidate_id,
                    title="反馈节奏与学习节奏",
                    summary="两个资料都在讨论用反馈调节节奏。",
                    relation_type="analogy",
                    reasoning="它们不是同名概念，但共享反馈调控结构。",
                    confidence=0.82,
                    novelty=0.77,
                )
            ]
        )

    report = asyncio.run(run_discovery(DiscoveryRequest(session_ids=[left, right]), judge=fake_judge))

    assert report.findings[0].title == "反馈节奏与学习节奏"
    assert report.findings[0].relation_type == "analogy"
    assert report.findings[0].confidence == 0.82
    assert "不是同名概念" in report.findings[0].reasoning


def test_run_discovery_uses_injected_titler_and_cleans_punctuation():
    left = _seed_session(course_title="A", lecture_title="资料一", concepts=[("概念A", [1.0, 0.0], "证据 A")])
    right = _seed_session(course_title="B", lecture_title="资料二", concepts=[("概念B", [0.8, 0.2], "证据 B")])

    async def fake_titler(prompt: str) -> str:
        return "《反馈与节奏》"  # wrapped in punctuation the engine should strip

    report = asyncio.run(run_discovery(DiscoveryRequest(session_ids=[left, right]), judge=None, titler=fake_titler))
    assert report.title == "反馈与节奏"


def test_run_discovery_falls_back_to_deterministic_title():
    left = _seed_session(course_title="A", lecture_title="资料一", concepts=[("启发式搜索", [1.0, 0.0], "证据 A")])
    right = _seed_session(course_title="B", lecture_title="资料二", concepts=[("候选召回", [0.8, 0.2], "证据 B")])

    report = asyncio.run(run_discovery(DiscoveryRequest(session_ids=[left, right]), judge=None, titler=None))
    assert report.title  # non-empty, readable, not the uuid
    assert report.title != report.discovery_id


def test_discovery_route_saves_and_loads_artifact():
    left = _seed_session(
        course_title="A",
        lecture_title="资料一",
        concepts=[("概念A", [1.0, 0.0], "证据 A")],
    )
    right = _seed_session(
        course_title="B",
        lecture_title="资料二",
        concepts=[("概念B", [0.8, 0.2], "证据 B")],
    )

    response = client.post(
        "/discovery/run",
        json={"session_ids": [str(left), str(right)], "mode": "selected", "limit": 3},
    )
    assert response.status_code == 200
    body = response.json()
    discovery_id = body["discovery_id"]
    assert body["findings"]
    assert local.discovery_path(discovery_id).exists()

    fetched = client.get(f"/discovery/{discovery_id}")
    assert fetched.status_code == 200
    assert fetched.json()["discovery_id"] == discovery_id
    listed = client.get("/discovery")
    assert listed.status_code == 200
    assert any(item["discovery_id"] == discovery_id for item in listed.json())


def test_random_discovery_without_session_ids_samples_built_sessions():
    _seed_session(course_title="A", lecture_title="资料一", concepts=[("概念A", [1.0, 0.0], "证据 A")])
    _seed_session(course_title="B", lecture_title="资料二", concepts=[("概念B", [0.8, 0.2], "证据 B")])

    response = client.post("/discovery/run", json={"mode": "random", "limit": 2, "seed": 7})

    assert response.status_code == 200
    body = response.json()
    assert body["mode"] == "random"
    assert len(body["session_ids"]) >= 2
    assert body["findings"]
    assert local.discovery_path(body["discovery_id"]).exists()


def test_discovery_rejects_empty_selected_request():
    response = client.post("/discovery/run", json={"mode": "selected", "session_ids": []})

    assert response.status_code == 400


def test_judged_finding_coerces_relation_type_to_enum():
    # Chinese label maps back to the canonical enum…
    assert JudgedFinding(candidate_id="cand-1", relation_type="类比").relation_type == "analogy"
    assert JudgedFinding(candidate_id="cand-1", relation_type="方法迁移").relation_type == "method_to_application"
    # …an already-canonical key is kept…
    assert JudgedFinding(candidate_id="cand-1", relation_type="contradiction").relation_type == "contradiction"
    # …and anything unrecognised falls back so the frontend label always resolves.
    finding = JudgedFinding(candidate_id="cand-1", relation_type="something the model invented")
    assert finding.relation_type in RELATION_TYPES
    assert finding.relation_type == "shared_context"


def test_discovery_batches_large_candidate_pool_and_merges():
    left = _seed_session(
        course_title="A",
        lecture_title="资料一",
        concepts=[(f"概念A{i}", [1.0 - i * 0.05, i * 0.05], f"证据 A{i}") for i in range(4)],
    )
    right = _seed_session(
        course_title="B",
        lecture_title="资料二",
        concepts=[(f"概念B{i}", [0.2 + i * 0.05, 0.8 - i * 0.05], f"证据 B{i}") for i in range(4)],
    )
    # 4×4 cross-session pairs = 16 candidates > _JUDGE_BATCH (12) → at least two batches.
    calls: list[str] = []

    async def counting_judge(prompt: str) -> JudgeReport:
        candidate_id = re.search(r"候选 (cand-\d+)", prompt).group(1)  # type: ignore[union-attr]
        calls.append(candidate_id)
        # Chinese relation label also exercises coercion through the pipeline.
        return JudgeReport(
            findings=[
                JudgedFinding(
                    candidate_id=candidate_id,
                    title=f"finding-{candidate_id}",
                    summary="batch finding",
                    relation_type="类比",
                    confidence=0.7,
                )
            ]
        )

    report = asyncio.run(
        run_discovery(DiscoveryRequest(session_ids=[left, right], limit=8), judge=counting_judge)
    )

    assert len(calls) >= 2  # batched into multiple judge calls
    assert report.findings
    assert all(f.relation_type in RELATION_TYPES for f in report.findings)
    assert report.findings[0].relation_type == "analogy"


def test_discovery_evidence_can_include_two_chunks_per_side():
    session_id = uuid.uuid4()
    session = CourseSession(session_id=session_id, course_title="证据", lecture_title="多片段", status=SessionStatus.graph_ready)
    local.save_session(session)
    other = _seed_session(course_title="对照", lecture_title="资料", concepts=[("对照概念", [0.1, 0.9], "对照证据")])
    source_id = uuid.uuid4()
    local.save_graph_artifact(
        GraphArtifact(
            session_id=session_id,
            concepts=[
                ConceptNode(
                    concept_id="concept:多片段",
                    name="背压",
                    canonical_name="背压",
                    summary="反馈限速",
                    definition="反馈限速",
                    embedding=[0.9, 0.1],
                    importance_score=0.9,
                )
            ],
            edges=[],
        )
    )
    # Two distinct chunks both mention the concept name → two evidence rows for that side.
    local.save_ingest_artifact(
        IngestArtifact(
            session_id=session_id,
            source_id=source_id,
            source_kind=SourceKind.document,
            chunks=[
                EvidenceChunk(chunk_id=f"{session_id}-0", source_id=str(source_id), source_type=SourceKind.document, text="背压用于限速。", summary="", embedding=[0.9, 0.1]),
                EvidenceChunk(chunk_id=f"{session_id}-1", source_id=str(source_id), source_type=SourceKind.document, text="背压避免队列膨胀。", summary="", embedding=[0.88, 0.12]),
            ],
        )
    )

    report = asyncio.run(run_discovery(DiscoveryRequest(session_ids=[session_id, other]), judge=None))

    finding = report.findings[0]
    from_multi = [e for e in finding.evidence if str(e.session_id) == str(session_id)]
    assert len(from_multi) >= 2  # both chunks surfaced as evidence for that concept


def test_random_discovery_ignores_virtual_course_graph_sessions():
    _seed_session(
        course_title="知识库",
        lecture_title="知识库",
        concepts=[("总图谱概念", [1.0, 0.0], "虚拟图谱")],
        virtual=True,
    )

    response = client.post("/discovery/run", json={"mode": "random", "limit": 2, "seed": 1})

    assert response.status_code == 400
