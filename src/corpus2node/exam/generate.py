"""Importance-driven level-test generation with an independent verifier loop.

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
from collections.abc import Awaitable, Callable

from corpus2node import prompt_store
from corpus2node.core.text import normalize_text
from corpus2node.core.types import (
    ConceptNode,
    EvidenceChunk,
    GraphArtifact,
    GenerateTestRequest,
    TestDocument,
    TestQuestion,
)
from corpus2node.exam.prompts import (
    EXAM_SYSTEM_PROMPT,
    SOLVER_SYSTEM_PROMPT,
    build_exam_prompt,
    build_solver_prompt,
)
from corpus2node.exam.schemas import LLMExamDocument, SolvedAnswer
from corpus2node.exam.validate import ALL_TYPES, answers_match, coerce_question
from corpus2node.index import search
from corpus2node.index.embeddings import ensure_embedding_compatible, get_embeddings
from corpus2node.llm import factory
from corpus2node.llm.credentials import Purpose
from corpus2node.llm.structured import make_structured
from corpus2node.notes.markdown import heading_key
from corpus2node.storage import local

logger = logging.getLogger(__name__)

ExamCaller = Callable[[str], Awaitable[LLMExamDocument]]
SolveCaller = Callable[[str], Awaitable[SolvedAnswer]]
OnQuestion = Callable[[TestQuestion], None]  # progressive streaming hook (verified questions)

GROUNDING_CHUNK_LIMIT = 3
VERIFY_CONCURRENCY = 8


async def generate_test(
    request: GenerateTestRequest,
    *,
    exam_caller: ExamCaller | None = None,
    solve_caller: SolveCaller | None = None,
    embeddings=None,
    verify: bool = True,
    max_rounds: int = 2,
    on_question: OnQuestion | None = None,
) -> TestDocument:
    graph = local.load_graph_artifact(request.session_id)
    session = local.load_session(request.session_id)
    if not graph.concepts:
        raise ValueError("No concepts available to generate test.")

    injected_embeddings = embeddings is not None
    embeddings = embeddings or get_embeddings()
    ensure_embedding_compatible(graph, embeddings, require_known=not injected_embeddings)
    chunks = [chunk for artifact in local.list_ingest_artifacts(request.session_id) for chunk in artifact.chunks]
    by_chunk_id = {chunk.chunk_id: chunk for chunk in chunks}
    valid_ids = {concept.concept_id for concept in graph.concepts}
    exam_caller, solve_caller = _ensure_callers(exam_caller, solve_caller, verify)
    targets = select_test_targets(graph, request.question_count)

    accepted_by_slot: dict[int, TestQuestion] = {}
    seen_keys: set[str] = set()
    title = ""
    summary = ""
    rejected = 0
    rounds = 0

    while len(accepted_by_slot) < request.question_count and rounds < max_rounds:
        rounds += 1
        remaining_slots = [(index, target) for index, target in enumerate(targets) if index not in accepted_by_slot]
        doc = await exam_caller(
            build_exam_prompt(
                graph,
                lecture_title=session.lecture_title,
                target_concepts=[target for _, target in remaining_slots],
                exclude_stems=[question.stem for question in accepted_by_slot.values()],
            )
        )
        title = title or normalize_text(doc.title).replace("试卷", "测试")
        summary = summary or normalize_text(doc.summary).replace("试卷", "测试")

        candidates: list[tuple[int, TestQuestion]] = []
        claimed_slots: set[int] = set()
        for question in doc.questions:
            slot = next(
                (
                    (index, target)
                    for index, target in remaining_slots
                    if index not in claimed_slots and target.concept_id in question.concept_ids
                ),
                None,
            )
            if slot is None:
                continue
            slot_index, target = slot
            coerced = coerce_question(
                question,
                valid_concept_ids=valid_ids,
                allowed_types=ALL_TYPES,
                primary_concept_id=target.concept_id,
                importance_score=target.importance_score,
            )
            if coerced is None:
                continue
            key = heading_key(coerced.stem)
            if not key or key in seen_keys:
                continue
            seen_keys.add(key)
            claimed_slots.add(slot_index)
            candidates.append((slot_index, coerced))

        if verify and solve_caller is not None and candidates:
            semaphore = asyncio.Semaphore(VERIFY_CONCURRENCY)

            async def _bounded(question: TestQuestion) -> bool:
                async with semaphore:
                    return await _verify(question, solve_caller, graph, chunks, embeddings, by_chunk_id)

            verdicts = await asyncio.gather(*(_bounded(question) for _, question in candidates))
            kept = [item for item, ok in zip(candidates, verdicts) if ok]
            rejected += len(candidates) - len(kept)
            candidates = kept

        for slot_index, question in candidates:
            accepted_by_slot[slot_index] = question
            if on_question is not None:
                on_question(question)
        logger.info(
            "test round %d: accepted=%d/%d, rejected_total=%d",
            rounds, len(accepted_by_slot), request.question_count, rejected,
        )

    questions = [accepted_by_slot[index] for index in sorted(accepted_by_slot)]
    if not questions:
        raise ValueError("Test LLM returned no usable questions.")

    test = TestDocument(
        session_id=request.session_id,
        title=title or f"{session.lecture_title} - 知识水平测试",
        summary=summary or f"按知识点重要度生成 {len(questions)} 道水平测试题。",
        questions=questions,
    )
    local.save_test(test)
    logger.info("test done: %d questions (%d rejected by verifier)", len(questions), rejected)
    return test


def select_test_targets(graph: GraphArtifact, question_count: int) -> list[ConceptNode]:
    """Choose the tested knowledge points deterministically from graph importance.

    The highest-ranked concepts are covered once first. If a very small graph needs
    more questions than it has concepts, extra slots cycle through the top half so
    higher-importance concepts receive deeper assessment.
    """
    ranked = sorted(graph.concepts, key=lambda concept: concept.importance_score, reverse=True)
    if not ranked or question_count <= 0:
        return []
    targets = ranked[:question_count]
    if len(targets) >= question_count:
        return targets
    repeat_pool = ranked[: max(1, (len(ranked) + 1) // 2)]
    while len(targets) < question_count:
        targets.append(repeat_pool[(len(targets) - len(ranked)) % len(repeat_pool)])
    return targets


# Compatibility alias for Python callers using the former product term.
generate_exam = generate_test


def _ensure_callers(
    exam_caller: ExamCaller | None, solve_caller: SolveCaller | None, verify: bool
) -> tuple[ExamCaller, SolveCaller | None]:
    if exam_caller is None:
        model = factory.build_chat_model(Purpose.exam)
        method = factory.structured_output_method(Purpose.exam)
        exam_caller = make_structured(model, LLMExamDocument, system=EXAM_SYSTEM_PROMPT + prompt_store.custom_block("exam"), method=method)
    if verify and solve_caller is None:
        model = factory.build_chat_model(Purpose.critic)  # critic falls back to graph
        method = factory.structured_output_method(Purpose.critic)
        solve_caller = make_structured(model, SolvedAnswer, system=SOLVER_SYSTEM_PROMPT, method=method)
    return exam_caller, solve_caller


async def _verify(
    question: TestQuestion,
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
        logger.exception("test verifier solve failed; keeping question")
        return True
    match = answers_match(question.question_type, solved.answer, question.answer)
    if match is None:  # subjective: trust grounding
        return bool(solved.grounded)
    return bool(match)


def _question_concepts(graph: GraphArtifact, question: TestQuestion) -> list[ConceptNode]:
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
