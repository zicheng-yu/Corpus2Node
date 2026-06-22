from __future__ import annotations

import asyncio
from pathlib import Path

from corpus2node.core.types import CourseSession, SessionStatus, SourceFile, SourceKind
from corpus2node.graph.schemas import ExtractedConcept, ExtractedRelation, GraphExtractionResult
from corpus2node.graph.workflow import run_workflow
from corpus2node.index.embeddings import HashingEmbeddings
from corpus2node.storage import local

FIXTURE = Path(__file__).parent / "fixtures" / "sample_lecture.md"


def _make_session() -> CourseSession:
    session = CourseSession(course_title="数据结构", lecture_title="树与查找")
    session.source_files.append(
        SourceFile(
            kind=SourceKind.pdf,  # multimodal kinds (md/pptx/...) come with the adapter batch
            filename="sample_lecture.md",
            content_type="text/markdown",
            storage_path=str(FIXTURE),
            size_bytes=FIXTURE.stat().st_size,
        )
    )
    local.save_session(session)
    return session


def _fake_candidates() -> GraphExtractionResult:
    return GraphExtractionResult(
        concepts=[
            ExtractedConcept(name="二叉搜索树", canonical_name="二叉搜索树", definition="一种用于高效查找的树结构"),
            ExtractedConcept(name="平衡树", canonical_name="平衡树", definition="二叉搜索树的改进，维持高度平衡"),
            ExtractedConcept(name="树结构", canonical_name="树结构", definition="层次型数据结构"),
        ],
        relations=[
            ExtractedRelation(
                source_canonical_name="二叉搜索树", target_canonical_name="树结构",
                edge_type="RELATES_TO", relation_type="is_a", confidence=0.9,
            ),
            ExtractedRelation(
                source_canonical_name="平衡树", target_canonical_name="二叉搜索树",
                edge_type="RELATES_TO", relation_type="is_a", confidence=0.85,
            ),
        ],
    )


def test_workflow_end_to_end_offline():
    session = _make_session()
    fixture_text = FIXTURE.read_text(encoding="utf-8")

    def fake_extract_blocks(source: SourceFile) -> list[str]:
        return [fixture_text]

    async def fake_astructured(prompt: str) -> GraphExtractionResult:
        return _fake_candidates()

    graph = asyncio.run(
        run_workflow(
            session.session_id,
            astructured=fake_astructured,
            embeddings=HashingEmbeddings(dims=128),
            extract_blocks=fake_extract_blocks,
        )
    )

    # graph produced and clustered
    assert graph.session_id == session.session_id
    assert len(graph.concepts) >= 2
    assert len(graph.edges) >= 2
    assert graph.topic_clusters
    assert all(concept.graph_metrics for concept in graph.concepts)

    # artifacts + session state persisted
    assert local.load_graph_artifact(session.session_id).concepts
    reloaded = local.load_session(session.session_id)
    assert reloaded.status == SessionStatus.graph_ready
    assert reloaded.stats.chunk_count > 0
    assert reloaded.stats.concept_count >= 2
    assert all(source.ingested for source in reloaded.source_files)


def test_workflow_requires_sources():
    session = CourseSession(course_title="空", lecture_title="空")
    local.save_session(session)
    try:
        asyncio.run(run_workflow(session.session_id, astructured=None, embeddings=HashingEmbeddings(dims=32)))
        raise AssertionError("expected ValueError for a session with no sources")
    except ValueError:
        pass
