from __future__ import annotations

import asyncio
import uuid

from corpus2node.core.types import (
    CourseSession,
    EvidenceChunk,
    GenerateNotesRequest,
    IngestArtifact,
    SessionStatus,
    SourceKind,
)
from corpus2node.graph.build import build_graph_artifact
from corpus2node.graph.schemas import ExtractedConcept, ExtractedRelation, GraphExtractionResult
from corpus2node.index.embeddings import HashingEmbeddings
from corpus2node.notes.generate import _coverage_repair, generate_notes
from corpus2node.notes.schemas import LLMNoteSection
from corpus2node.storage import local

EMB = HashingEmbeddings(dims=256)


def _setup_graph() -> uuid.UUID:
    session = CourseSession(course_title="数据结构", lecture_title="树")
    local.save_session(session)
    chunks = [
        EvidenceChunk(
            chunk_id=f"s-c{i}", source_id="s", source_type=SourceKind.pdf,
            text=text, summary=text[:8], embedding=EMB.embed_query(text), page_start=i + 1,
        )
        for i, text in enumerate(["二叉搜索树 是 一种 树 ，用于 高效 查找", "平衡树 是 二叉搜索树 的 改进"])
    ]
    local.save_ingest_artifact(
        IngestArtifact(session_id=session.session_id, source_id=uuid.uuid4(), source_kind=SourceKind.pdf, chunks=chunks)
    )
    candidates = GraphExtractionResult(
        concepts=[
            ExtractedConcept(name="二叉搜索树", canonical_name="二叉搜索树", definition="用于 查找 的 树"),
            ExtractedConcept(name="平衡树", canonical_name="平衡树", definition="二叉搜索树 的 改进"),
            ExtractedConcept(name="树结构", canonical_name="树结构", definition="层次 数据 结构"),
        ],
        relations=[
            ExtractedRelation(
                source_canonical_name="二叉搜索树", target_canonical_name="树结构",
                edge_type="RELATES_TO", relation_type="is_a", confidence=0.9,
            )
        ],
    )
    local.save_graph_artifact(build_graph_artifact(session.session_id, chunks, candidates, embeddings=EMB))
    return session.session_id


def test_generate_notes_happy_path_cleans_and_numbers_and_persists():
    session_id = _setup_graph()
    calls: list[str] = []

    async def section_caller(prompt: str) -> LLMNoteSection:
        calls.append(prompt)
        # escaped newlines + a duplicate heading the cleaner must repair
        return LLMNoteSection(title="二叉搜索树：如何查找", content_md="**关键结论**\\n- 高效查找\\n- 有序遍历", concept_ids=[])

    async def summary_caller(prompt: str) -> str:
        return "本笔记围绕树结构展开。"

    note = asyncio.run(
        generate_notes(
            GenerateNotesRequest(session_id=session_id),
            section_caller=section_caller,
            summary_caller=summary_caller,
            embeddings=EMB,
            max_repair_rounds=0,
        )
    )

    assert note.sections, "expected at least one section"
    assert calls, "section_caller should have been invoked (map step)"
    assert note.sections[0].title.startswith("第 1 节："), "sections should be numbered"
    assert "\\n" not in note.sections[0].content_md, "escaped newlines should be repaired"
    assert "\n" in note.sections[0].content_md
    assert note.summary == "本笔记围绕树结构展开。"
    # grounding: each section retrieved against source chunks → references attached (excluded from wire)
    assert any(section.references for section in note.sections)

    reloaded = local.load_note(session_id)
    assert reloaded.note_id == note.note_id
    assert local.load_session(session_id).status == SessionStatus.notes_ready


def test_coverage_critic_fills_uncovered_core_concepts():
    session_id = _setup_graph()
    graph = local.load_graph_artifact(session_id)
    calls: list[str] = []

    async def section_caller(prompt: str) -> LLMNoteSection:
        calls.append(prompt)
        return LLMNoteSection(title="补充：未覆盖要点", content_md="- 补充内容", concept_ids=[])

    raw: list = []
    covered_ids: set[str] = set()  # nothing covered yet → all core concepts missing
    covered_names: list[str] = []

    asyncio.run(
        _coverage_repair(
            graph,
            raw,
            section_caller=section_caller,
            chunks=[],
            embeddings=EMB,
            by_chunk_id={},
            lecture_title="树",
            topic_pref="",
            covered_ids=covered_ids,
            covered_names=covered_names,
            max_rounds=1,
        )
    )

    assert calls, "coverage critic should call the section_caller to fill gaps"
    assert len(raw) == 1, "one bounded repair section should be appended"
    assert covered_ids, "covered set should grow after the fill"
