from __future__ import annotations

import asyncio
import re
import uuid

import pytest

from corpus2node.core.types import (
    CourseSession,
    EvidenceChunk,
    GenerateTestRequest,
    IngestArtifact,
    SourceKind,
)
from corpus2node.exam.generate import generate_test, select_test_targets
from corpus2node.exam.schemas import LLMExamChoice, LLMExamDocument, LLMExamQuestion, SolvedAnswer
from corpus2node.graph.build import build_graph_artifact
from corpus2node.graph.schemas import ExtractedConcept, ExtractedRelation, GraphExtractionResult
from corpus2node.index.embeddings import HashingEmbeddings
from corpus2node.storage import local

EMB = HashingEmbeddings(dims=256)


def _setup_graph() -> tuple[uuid.UUID, str]:
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
    graph = build_graph_artifact(session.session_id, chunks, candidates, embeddings=EMB)
    local.save_graph_artifact(graph)
    return session.session_id, graph.concepts[0].concept_id


def _q(stem: str, answer: str, concept_id: str, qtype: str = "short_answer") -> LLMExamQuestion:
    choices = [LLMExamChoice(choice_id=c, text=f"opt {c}") for c in "ABCD"] if qtype in {"single_choice", "multiple_choice"} else []
    return LLMExamQuestion(
        question_type=qtype, stem=stem, answer=answer, explanation="因为如此", concept_ids=[concept_id], choices=choices
    )


def _target_ids(prompt: str) -> list[str]:
    return re.findall(r"primary_concept_id=([^ |\n]+)", prompt)


def test_generate_test_returns_requested_count_despite_invalid_questions():
    """Donor bug: invalid questions were dropped then sliced, yielding < requested. We top up."""
    session_id, _ = _setup_graph()

    rounds = 0

    async def exam_caller(prompt: str) -> LLMExamDocument:
        nonlocal rounds
        rounds += 1
        questions = [_q(f"知识点 {index} 的用途是什么？", "用于解决问题", cid) for index, cid in enumerate(_target_ids(prompt))]
        if rounds == 1:
            questions[0] = LLMExamQuestion(question_type="short_answer", stem="", answer="", explanation="")
        return LLMExamDocument(
            title="树水平测试", summary="覆盖核心", questions=questions,
        )

    test = asyncio.run(
        generate_test(
            GenerateTestRequest(session_id=session_id, question_count=4),
            exam_caller=exam_caller,
            verify=False,
            embeddings=EMB,
        )
    )
    assert len(test.questions) == 4
    assert all(q.stem for q in test.questions)
    assert all(q.primary_concept_id == q.concept_ids[0] for q in test.questions)
    assert rounds == 2


def test_verifier_rejects_wrong_answer_and_tops_up():
    session_id, _ = _setup_graph()
    rounds: list[int] = []

    async def exam_caller(prompt: str) -> LLMExamDocument:
        rounds.append(1)
        questions = [
            _q(f"Q-good{index}: 正确答案的题", "A", cid, qtype="single_choice")
            for index, cid in enumerate(_target_ids(prompt))
        ]
        if len(rounds) == 1:
            questions[0].stem = "Q-bad: 错误答案的题"
        return LLMExamDocument(questions=questions)

    async def solve_caller(prompt: str) -> SolvedAnswer:
        # the solver disagrees only with the "bad" question
        return SolvedAnswer(answer="B" if "Q-bad" in prompt else "A", grounded=True)

    test = asyncio.run(
        generate_test(
            GenerateTestRequest(session_id=session_id, question_count=4),
            exam_caller=exam_caller,
            solve_caller=solve_caller,
            verify=True,
            embeddings=EMB,
            max_rounds=2,
        )
    )
    assert len(test.questions) == 4
    assert all("Q-bad" not in q.stem for q in test.questions)
    assert len(rounds) == 2  # a second generation round was needed to replace the rejected question


def test_generate_test_streams_questions_via_callback():
    session_id, _ = _setup_graph()
    streamed = []

    async def exam_caller(prompt: str) -> LLMExamDocument:
        return LLMExamDocument(
            questions=[_q(f"Q{i}?", f"A{i}", cid) for i, cid in enumerate(_target_ids(prompt))]
        )

    asyncio.run(
        generate_test(
            GenerateTestRequest(session_id=session_id, question_count=4),
            exam_caller=exam_caller,
            verify=False,
            embeddings=EMB,
            on_question=lambda q: streamed.append(q),
        )
    )
    assert len(streamed) == 4  # each accepted question streamed progressively


def test_verifier_rejects_ungrounded_subjective():
    session_id, _ = _setup_graph()

    async def exam_caller(prompt: str) -> LLMExamDocument:
        return LLMExamDocument(
            questions=[_q(f"无法从资料作答的题 {index}？", "凭空答案", cid) for index, cid in enumerate(_target_ids(prompt))]
        )

    async def solve_caller(prompt: str) -> SolvedAnswer:
        return SolvedAnswer(answer="不确定", grounded=False)  # can't ground → reject

    # the only question is ungroundable → rejected → nothing usable remains
    with pytest.raises(ValueError, match="no usable questions"):
        asyncio.run(
            generate_test(
                GenerateTestRequest(session_id=session_id, question_count=4),
                exam_caller=exam_caller,
                solve_caller=solve_caller,
                verify=True,
                embeddings=EMB,
                max_rounds=1,
            )
        )


def test_select_test_targets_prioritizes_importance_and_repeats_core_concepts():
    session_id, _ = _setup_graph()
    graph = local.load_graph_artifact(session_id)

    targets = select_test_targets(graph, 5)

    ranked = sorted(graph.concepts, key=lambda concept: concept.importance_score, reverse=True)
    assert targets[: len(ranked)] == ranked
    assert all(target in ranked[:2] for target in targets[len(ranked):])
