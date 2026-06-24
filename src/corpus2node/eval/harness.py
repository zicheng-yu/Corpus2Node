"""Eval orchestration: deterministic metrics from saved artifacts + optional LLM runners.

The deterministic evals (extraction / notes / exam) read the on-disk artifacts and
need no LLM, so they're cheap and fully testable. The LLM runners (QA grounding,
exam answer-key agreement) reuse the live chat agent / exam solver and cost tokens.
"""
from __future__ import annotations

import asyncio
import logging
from uuid import UUID

from corpus2node.core.types import EdgeType, ExamDocument, GraphArtifact, NoteDocument
from corpus2node.eval import metrics
from corpus2node.eval.schemas import EvalReport, ExamEval, ExtractionEval, GoldDataset, NotesEval, QAEval
from corpus2node.exam.validate import OBJECTIVE_TYPES
from corpus2node.storage import local

logger = logging.getLogger(__name__)


def evaluate_extraction(graph: GraphArtifact, gold: GoldDataset) -> ExtractionEval:
    pred = [metrics.keys(c.name, c.canonical_name, *c.aliases) for c in graph.concepts]
    gold_keysets = [metrics.keys(g.name, *g.aliases) for g in gold.concepts]
    precision, recall, f1, matched_pred, matched_gold = metrics.concept_prf(pred, gold_keysets)

    id_keys = {c.concept_id: metrics.keys(c.name, c.canonical_name, *c.aliases) for c in graph.concepts}
    semantic = [edge for edge in graph.edges if metrics.edge_type_value(edge) == EdgeType.relates_to.value]
    matched_rel = 0
    for relation in gold.relations:
        source_keys, target_keys = metrics.keys(relation.source), metrics.keys(relation.target)
        if any(
            (id_keys.get(edge.source, set()) & source_keys and id_keys.get(edge.target, set()) & target_keys)
            or (id_keys.get(edge.source, set()) & target_keys and id_keys.get(edge.target, set()) & source_keys)
            for edge in semantic
        ):
            matched_rel += 1
    rel_recall = matched_rel / len(gold.relations) if gold.relations else 0.0

    return ExtractionEval(
        predicted_concepts=len(graph.concepts),
        gold_concepts=len(gold.concepts),
        matched_predicted=matched_pred,
        matched_gold=matched_gold,
        concept_precision=round(precision, 3),
        concept_recall=round(recall, 3),
        concept_f1=round(f1, 3),
        edges=len(graph.edges),
        relation_validity_rate=round(metrics.relation_validity_rate(graph.edges), 3),
        relation_recall=round(rel_recall, 3),
    )


def evaluate_notes(note: NoteDocument, graph: GraphArtifact) -> NotesEval:
    course_ids = set(graph.course_meta.core_concept_ids) if graph.course_meta else None
    core = metrics.core_concepts(graph.concepts, course_ids)
    covered_ids = {cid for section in note.sections for cid in section.concept_ids}
    covered = sum(1 for concept in core if concept.concept_id in covered_ids)
    return NotesEval(
        core_concepts=len(core),
        covered=covered,
        coverage=round(covered / len(core), 3) if core else 0.0,
        sections=len(note.sections),
    )


def evaluate_exam(exam: ExamDocument) -> ExamEval:
    questions = exam.questions
    traceable = sum(1 for question in questions if question.concept_ids)
    objective = [question for question in questions if question.question_type in OBJECTIVE_TYPES]
    objective_valid = sum(1 for question in objective if metrics.objective_answer_valid(question))
    return ExamEval(
        questions=len(questions),
        traceable=traceable,
        traceability=round(traceable / len(questions), 3) if questions else 0.0,
        objective=len(objective),
        objective_valid=objective_valid,
        objective_validity=round(objective_valid / len(objective), 3) if objective else 0.0,
    )


def evaluate_qa(turns) -> QAEval:
    """turns: objects exposing .answer (str) and .citations (list of ChatCitation)."""
    total = len(turns)
    answered = sum(1 for turn in turns if (turn.answer or "").strip())
    grounded = sum(1 for turn in turns if turn.citations)
    chunk_grounded = sum(1 for turn in turns if any(c.kind == "chunk" for c in turn.citations))
    citations = sum(len(turn.citations) for turn in turns)
    return QAEval(
        questions=total,
        answered=answered,
        grounded=grounded,
        groundedness=round(grounded / total, 3) if total else 0.0,
        chunk_grounded=chunk_grounded,
        avg_citations=round(citations / total, 2) if total else 0.0,
    )


def run_offline_report(session_id: UUID, gold: GoldDataset | None = None) -> EvalReport:
    """Deterministic evals from the saved artifacts (no LLM). Raises if no graph exists."""
    report = EvalReport(session_id=session_id)
    graph = local.load_graph_artifact(session_id)
    if gold is not None:
        report.extraction = evaluate_extraction(graph, gold)
    try:
        report.notes = evaluate_notes(local.load_note(session_id), graph)
    except FileNotFoundError:
        pass
    try:
        report.exam = evaluate_exam(local.load_exam(session_id))
    except FileNotFoundError:
        pass
    return report


# ── LLM runners (cost tokens; reuse the live agent / solver) ──────────────────


async def run_qa_eval(session_id: UUID, questions: list[str], *, model=None, embeddings=None) -> QAEval:
    from corpus2node.assistant import agent as chat_agent
    from corpus2node.index.embeddings import get_embeddings
    from corpus2node.llm import factory
    from corpus2node.llm.credentials import Purpose

    embeddings = embeddings or get_embeddings()
    model = model or factory.build_chat_model(Purpose.chat)
    turns = []
    for question in questions:
        ctx = chat_agent.load_context(session_id, embeddings)  # fresh per question (independence)
        turns.append(await chat_agent.run_chat(question, ctx, model=model))
    return evaluate_qa(turns)


async def run_exam_answer_key_eval(session_id: UUID, *, model=None, embeddings=None) -> float:
    """Answer-key agreement: an independent solver re-answers each saved question."""
    from corpus2node.exam.generate import _verify
    from corpus2node.exam.prompts import SOLVER_SYSTEM_PROMPT
    from corpus2node.exam.schemas import SolvedAnswer
    from corpus2node.index.embeddings import get_embeddings
    from corpus2node.llm import factory
    from corpus2node.llm.credentials import Purpose
    from corpus2node.llm.structured import make_structured

    embeddings = embeddings or get_embeddings()
    exam = local.load_exam(session_id)
    graph = local.load_graph_artifact(session_id)
    chunks = [chunk for artifact in local.list_ingest_artifacts(session_id) for chunk in artifact.chunks]
    by_chunk_id = {chunk.chunk_id: chunk for chunk in chunks}
    model = model or factory.build_chat_model(Purpose.critic)
    method = factory.structured_output_method(Purpose.critic)
    solve_caller = make_structured(model, SolvedAnswer, system=SOLVER_SYSTEM_PROMPT, method=method)

    verdicts = await asyncio.gather(
        *(_verify(question, solve_caller, graph, chunks, embeddings, by_chunk_id) for question in exam.questions)
    )
    return round(sum(1 for ok in verdicts if ok) / len(verdicts), 3) if verdicts else 0.0
