"""Exam generation with a verifier loop (§4: workflow + verifier, not role-play agents).

generator → an independent solver re-answers each question from the graph/原文 → questions
whose key the solver disagrees with (objective) or can't ground (subjective) are rejected,
and the shortfall is regenerated. Two things this buys over the donor:

1. Returns the requested count. The donor `continue`-skipped invalid questions then
   sliced `[:n]`, so a few bad questions meant fewer questions than asked. Here we
   count accepted questions and top up across bounded rounds.
2. A measurable quality gate: rejected-question counts are logged; the solver is a
   different purpose (critic, → graph fallback) so it isn't the generator grading itself.

Seams (exam_caller / solve_caller) are injectable for offline tests.
"""
from __future__ import annotations

import asyncio
import logging
import math
from collections.abc import Awaitable, Callable

from corpus2node.core.text import normalize_text
from corpus2node.core.types import (
    ConceptNode,
    EvidenceChunk,
    ExamDocument,
    ExamQuestion,
    GenerateExamRequest,
    GraphArtifact,
)
from corpus2node.exam.prompts import (
    EXAM_SYSTEM_PROMPT,
    SOLVER_SYSTEM_PROMPT,
    build_exam_prompt,
    build_solver_prompt,
)
from corpus2node.exam.schemas import LLMExamDocument, SolvedAnswer
from corpus2node.exam.validate import answers_match, coerce_question, normalize_question_types
from corpus2node.index import search
from corpus2node.index.embeddings import get_embeddings
from corpus2node.llm import factory
from corpus2node.llm.credentials import Purpose
from corpus2node.llm.structured import make_structured
from corpus2node.notes.markdown import heading_key
from corpus2node.storage import local

logger = logging.getLogger(__name__)

ExamCaller = Callable[[str], Awaitable[LLMExamDocument]]
SolveCaller = Callable[[str], Awaitable[SolvedAnswer]]
OnQuestion = Callable[[ExamQuestion], None]  # progressive streaming hook (verified questions)

OVERASK = 1.4
GROUNDING_CHUNK_LIMIT = 3
VERIFY_CONCURRENCY = 8


async def generate_exam(
    request: GenerateExamRequest,
    *,
    exam_caller: ExamCaller | None = None,
    solve_caller: SolveCaller | None = None,
    embeddings=None,
    verify: bool = True,
    max_rounds: int = 2,
    on_question: OnQuestion | None = None,
) -> ExamDocument:
    graph = local.load_graph_artifact(request.session_id)
    session = local.load_session(request.session_id)
    if not graph.concepts:
        raise ValueError("No concepts available to generate exam.")

    embeddings = embeddings or get_embeddings()
    chunks = [chunk for artifact in local.list_ingest_artifacts(request.session_id) for chunk in artifact.chunks]
    by_chunk_id = {chunk.chunk_id: chunk for chunk in chunks}
    valid_ids = {concept.concept_id for concept in graph.concepts}
    allowed = normalize_question_types(request.question_types)
    exam_caller, solve_caller = _ensure_callers(exam_caller, solve_caller, verify)

    accepted: list[ExamQuestion] = []
    seen_keys: set[str] = set()
    title = ""
    summary = ""
    rejected = 0
    rounds = 0

    while len(accepted) < request.question_count and rounds < max_rounds:
        rounds += 1
        need = request.question_count - len(accepted)
        batch_n = need if rounds > 1 else min(need + 8, max(need, math.ceil(need * OVERASK)))
        doc = await exam_caller(
            build_exam_prompt(
                graph,
                lecture_title=session.lecture_title,
                question_count=batch_n,
                allowed_types=allowed,
                exclude_stems=[question.stem for question in accepted],
            )
        )
        title = title or normalize_text(doc.title)
        summary = summary or normalize_text(doc.summary)

        candidates: list[ExamQuestion] = []
        for question in doc.questions:
            coerced = coerce_question(question, valid_concept_ids=valid_ids, allowed_types=allowed)
            if coerced is None:
                continue
            key = heading_key(coerced.stem)
            if not key or key in seen_keys:
                continue
            seen_keys.add(key)
            candidates.append(coerced)

        if verify and solve_caller is not None and candidates:
            semaphore = asyncio.Semaphore(VERIFY_CONCURRENCY)

            async def _bounded(question: ExamQuestion) -> bool:
                async with semaphore:
                    return await _verify(question, solve_caller, graph, chunks, embeddings, by_chunk_id)

            verdicts = await asyncio.gather(*(_bounded(question) for question in candidates))
            kept = [question for question, ok in zip(candidates, verdicts) if ok]
            rejected += len(candidates) - len(kept)
            candidates = kept

        for question in candidates:
            accepted.append(question)
            if on_question is not None:
                on_question(question)
            if len(accepted) >= request.question_count:
                break
        logger.info(
            "exam round %d: accepted=%d/%d, rejected_total=%d",
            rounds, len(accepted), request.question_count, rejected,
        )

    questions = accepted[: request.question_count]
    if not questions:
        raise ValueError("Exam LLM returned no usable questions.")

    exam = ExamDocument(
        session_id=request.session_id,
        title=title or f"{session.lecture_title} - 图谱试卷",
        summary=summary or f"基于当前图数据库生成 {len(questions)} 道题。",
        questions=questions,
    )
    local.save_exam(exam)
    logger.info("exam done: %d questions (%d rejected by verifier)", len(questions), rejected)
    return exam


def _ensure_callers(
    exam_caller: ExamCaller | None, solve_caller: SolveCaller | None, verify: bool
) -> tuple[ExamCaller, SolveCaller | None]:
    if exam_caller is None:
        model = factory.build_chat_model(Purpose.exam)
        method = factory.structured_output_method(Purpose.exam)
        exam_caller = make_structured(model, LLMExamDocument, system=EXAM_SYSTEM_PROMPT, method=method)
    if verify and solve_caller is None:
        model = factory.build_chat_model(Purpose.critic)  # critic falls back to graph
        method = factory.structured_output_method(Purpose.critic)
        solve_caller = make_structured(model, SolvedAnswer, system=SOLVER_SYSTEM_PROMPT, method=method)
    return exam_caller, solve_caller


async def _verify(
    question: ExamQuestion,
    solve_caller: SolveCaller,
    graph: GraphArtifact,
    chunks: list[EvidenceChunk],
    embeddings,
    by_chunk_id: dict[str, EvidenceChunk],
) -> bool:
    """Independent solve → keep if the solver agrees (objective) or can ground it (subjective)."""
    concepts = _question_concepts(graph, question)
    query = " ".join([question.stem, *(concept.name for concept in concepts[:3])])
    grounding = _grounding_chunks(query, chunks, embeddings, by_chunk_id)
    try:
        solved = await solve_caller(build_solver_prompt(question, concepts=concepts, grounding_chunks=grounding))
    except Exception:  # a flaky verify call must not sink the question — keep it
        logger.exception("exam verifier solve failed; keeping question")
        return True
    match = answers_match(question.question_type, solved.answer, question.answer)
    if match is None:  # subjective: trust grounding
        return bool(solved.grounded)
    return bool(match)


def _question_concepts(graph: GraphArtifact, question: ExamQuestion) -> list[ConceptNode]:
    by_id = {concept.concept_id: concept for concept in graph.concepts}
    return [by_id[cid] for cid in question.concept_ids if cid in by_id]


def _grounding_chunks(
    query: str,
    chunks: list[EvidenceChunk],
    embeddings,
    by_chunk_id: dict[str, EvidenceChunk],
    *,
    limit: int = GROUNDING_CHUNK_LIMIT,
) -> list[EvidenceChunk]:
    if not chunks or not query.strip():
        return []
    results = search.retrieve_chunks(query, chunks=chunks, embeddings=embeddings, limit=limit)
    return [by_chunk_id[result.ref_id] for result in results if result.ref_id in by_chunk_id]
