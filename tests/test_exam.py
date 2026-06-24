from __future__ import annotations

import asyncio
import uuid

import pytest

from corpus2node.core.types import (
    CourseSession,
    EvidenceChunk,
    GenerateExamRequest,
    IngestArtifact,
    SourceKind,
)
from corpus2node.exam.generate import generate_exam
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


def test_generate_exam_returns_requested_count_despite_invalid_questions():
    """Donor bug: invalid questions were dropped then sliced, yielding < requested. We top up."""
    session_id, vid = _setup_graph()

    async def exam_caller(prompt: str) -> LLMExamDocument:
        return LLMExamDocument(
            title="树测验", summary="覆盖核心",
            questions=[
                _q("二叉搜索树的用途是什么？", "高效查找", vid),
                _q("平衡树解决了什么问题？", "退化为链表", vid),
                LLMExamQuestion(question_type="short_answer", stem="", answer="", explanation=""),  # invalid → dropped
                _q("树结构有什么特点？", "层次结构", vid),
                _q("二叉搜索树和平衡树的区别？", "是否自平衡", vid),
            ],
        )

    exam = asyncio.run(
        generate_exam(
            GenerateExamRequest(session_id=session_id, question_count=4, question_types=["short_answer"]),
            exam_caller=exam_caller,
            verify=False,
            embeddings=EMB,
        )
    )
    assert len(exam.questions) == 4  # exactly the requested count, the invalid one didn't reduce it
    assert all(q.stem for q in exam.questions)


def test_verifier_rejects_wrong_answer_and_tops_up():
    session_id, vid = _setup_graph()
    rounds: list[int] = []

    async def exam_caller(prompt: str) -> LLMExamDocument:
        rounds.append(1)
        if len(rounds) == 1:
            return LLMExamDocument(questions=[
                _q("Q-bad: 错误答案的题", "A", vid, qtype="single_choice"),
                _q("Q-good1: 正确答案的题一", "A", vid, qtype="single_choice"),
                _q("Q-good2: 正确答案的题二", "A", vid, qtype="single_choice"),
                _q("Q-good3: 正确答案的题三", "A", vid, qtype="single_choice"),
            ])
        return LLMExamDocument(questions=[_q("Q-extra: 补充的题", "A", vid, qtype="single_choice")])

    async def solve_caller(prompt: str) -> SolvedAnswer:
        # the solver disagrees only with the "bad" question
        return SolvedAnswer(answer="B" if "Q-bad" in prompt else "A", grounded=True)

    exam = asyncio.run(
        generate_exam(
            GenerateExamRequest(session_id=session_id, question_count=4, question_types=["single_choice"]),
            exam_caller=exam_caller,
            solve_caller=solve_caller,
            verify=True,
            embeddings=EMB,
            max_rounds=2,
        )
    )
    assert len(exam.questions) == 4  # bad one rejected, then topped up to the requested count
    assert all("Q-bad" not in q.stem for q in exam.questions)
    assert len(rounds) == 2  # a second generation round was needed to replace the rejected question


def test_generate_exam_streams_questions_via_callback():
    session_id, vid = _setup_graph()
    streamed = []

    async def exam_caller(prompt: str) -> LLMExamDocument:
        return LLMExamDocument(questions=[_q(f"Q{i}?", f"A{i}", vid) for i in range(4)])

    asyncio.run(
        generate_exam(
            GenerateExamRequest(session_id=session_id, question_count=4, question_types=["short_answer"]),
            exam_caller=exam_caller,
            verify=False,
            embeddings=EMB,
            on_question=lambda q: streamed.append(q),
        )
    )
    assert len(streamed) == 4  # each accepted question streamed progressively


def test_verifier_rejects_ungrounded_subjective():
    session_id, vid = _setup_graph()

    async def exam_caller(prompt: str) -> LLMExamDocument:
        return LLMExamDocument(questions=[_q("无法从资料作答的题？", "凭空答案", vid)])

    async def solve_caller(prompt: str) -> SolvedAnswer:
        return SolvedAnswer(answer="不确定", grounded=False)  # can't ground → reject

    # the only question is ungroundable → rejected → nothing usable remains
    with pytest.raises(ValueError, match="no usable questions"):
        asyncio.run(
            generate_exam(
                GenerateExamRequest(session_id=session_id, question_count=4, question_types=["short_answer"]),
                exam_caller=exam_caller,
                solve_caller=solve_caller,
                verify=True,
                embeddings=EMB,
                max_rounds=1,
            )
        )
