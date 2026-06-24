"""Map-reduce note generation with a deterministic coverage critic.

§4: notes are *not* a free agent — they need stable structure, coverage guarantees
and reproducibility. So this is a workflow, not a ReAct loop:

  map     one grounded section per topic subgraph (clusters → core concepts), run
          sequentially so each section can carry-forward what's already covered.
  critic  deterministic coverage check: which high-importance / core concepts did
          no section touch? a bounded LLM "fill" pass adds sections for the gaps.
  reduce  a 导读 summary over the final section titles.

Grounding (new vs. donor): each section is retrieved against the source chunks and
those chunks are fed into the prompt + stored on the section (excluded from wire)
for traceability / a future groundedness metric.

The LLM seams are injectable (section_caller / summary_caller) so the whole thing
runs offline in tests; defaults are built from the credential registry (Purpose.graph).
"""
from __future__ import annotations

import logging
from collections import defaultdict
from collections.abc import Awaitable, Callable

from corpus2node.core.clock import utcnow
from corpus2node.core.text import normalize_text
from corpus2node.core.types import (
    ConceptNode,
    EvidenceChunk,
    GenerateNotesRequest,
    GraphArtifact,
    GraphEdge,
    NoteDocument,
    NoteReference,
    SessionStatus,
)
from corpus2node.index import search
from corpus2node.index.embeddings import get_embeddings
from corpus2node.llm import factory
from corpus2node.llm.credentials import Purpose
from corpus2node.llm.structured import make_structured
from corpus2node.notes.markdown import clean_section_markdown, coerce_note_sections, number_sections
from corpus2node.notes.prompts import (
    SECTION_SYSTEM_PROMPT,
    SUMMARY_SYSTEM_PROMPT,
    build_section_prompt,
    build_summary_prompt,
)
from corpus2node.notes.schemas import LLMNoteSection, LLMNoteSummary
from corpus2node.storage import local

logger = logging.getLogger(__name__)

SectionCaller = Callable[[str], Awaitable[LLMNoteSection]]
SummaryCaller = Callable[[str], Awaitable[str]]
OnSection = Callable[[str, str], None]  # (title, content_md) — progressive streaming hook


def _emit_section(on_section: OnSection | None, llm_section: LLMNoteSection) -> None:
    if on_section is None:
        return
    title = normalize_text(getattr(llm_section, "title", "")) or "学习笔记"
    on_section(title, clean_section_markdown(getattr(llm_section, "title", ""), getattr(llm_section, "content_md", "")))

CORE_CONCEPT_LIMIT = 15
SECTION_MAX_CONCEPTS = 12
SECTION_MAX_NEIGHBORS = 6
GROUNDING_CHUNK_LIMIT = 3
COVERAGE_FILL_BATCH = 8


async def generate_notes(
    request: GenerateNotesRequest,
    *,
    section_caller: SectionCaller | None = None,
    summary_caller: SummaryCaller | None = None,
    embeddings=None,
    max_repair_rounds: int = 1,
    on_section: OnSection | None = None,
) -> NoteDocument:
    graph = local.load_graph_artifact(request.session_id)
    session = local.load_session(request.session_id)
    if not graph.concepts:
        raise ValueError("No concepts available to generate notes.")

    embeddings = embeddings or get_embeddings()
    chunks = [chunk for artifact in local.list_ingest_artifacts(request.session_id) for chunk in artifact.chunks]
    by_chunk_id = {chunk.chunk_id: chunk for chunk in chunks}
    valid_ids = {concept.concept_id for concept in graph.concepts}
    section_caller, summary_caller = _ensure_callers(section_caller, summary_caller)

    topics = _section_topics(graph)
    total = len(topics)
    raw_sections: list[tuple[LLMNoteSection, list[NoteReference]]] = []
    covered_ids: set[str] = set()
    covered_names: list[str] = []

    for index, (_, concept_ids) in enumerate(topics, start=1):
        concepts, edges = _topic_subgraph(graph, concept_ids)
        if not concepts:
            continue
        grounding = _grounding_chunks(concepts, chunks, embeddings, by_chunk_id)
        prompt = build_section_prompt(
            lecture_title=session.lecture_title,
            topic_pref=request.topic,
            section_index=index,
            total_sections=total,
            core_name=concepts[0].name,
            concepts=concepts,
            edges=edges,
            grounding_chunks=grounding,
            covered_concepts=covered_names,
        )
        llm_section = await section_caller(prompt)
        _emit_section(on_section, llm_section)
        raw_sections.append((llm_section, [_reference(chunk) for chunk in grounding]))
        covered_ids.update(concept.concept_id for concept in concepts)
        covered_names.extend(concept.name for concept in concepts)
        logger.info("notes section %d/%d generated", index, total)

    await _coverage_repair(
        graph,
        raw_sections,
        section_caller=section_caller,
        chunks=chunks,
        embeddings=embeddings,
        by_chunk_id=by_chunk_id,
        lecture_title=session.lecture_title,
        topic_pref=request.topic,
        covered_ids=covered_ids,
        covered_names=covered_names,
        max_rounds=max_repair_rounds,
        on_section=on_section,
    )

    refs_by_index = {index: refs for index, (_, refs) in enumerate(raw_sections)}
    sections = coerce_note_sections(
        [section for section, _ in raw_sections],
        valid_concept_ids=valid_ids,
        references_by_index=refs_by_index,
    )
    if not sections:
        raise ValueError("Notes LLM returned no usable sections.")
    sections = number_sections(sections)

    summary = await summary_caller(
        build_summary_prompt(
            lecture_title=session.lecture_title,
            topic_pref=request.topic,
            section_titles=[section.title for section in sections],
        )
    )

    note = NoteDocument(
        session_id=request.session_id,
        title=f"{session.lecture_title} - 图谱笔记",
        topic=normalize_text(request.topic) or "当前知识图谱",
        summary=normalize_text(summary) or f"基于当前图数据库整理出 {len(sections)} 个主题段落。",
        sections=sections,
    )
    local.save_note(note)
    session.status = SessionStatus.notes_ready
    session.error_message = None
    session.updated_at = utcnow()
    local.save_session(session)
    logger.info("notes done: %d sections", len(sections))
    return note


def _ensure_callers(
    section_caller: SectionCaller | None, summary_caller: SummaryCaller | None
) -> tuple[SectionCaller, SummaryCaller]:
    if section_caller is not None and summary_caller is not None:
        return section_caller, summary_caller
    model = factory.build_chat_model(Purpose.graph)
    method = factory.structured_output_method(Purpose.graph)
    if section_caller is None:
        section_caller = make_structured(model, LLMNoteSection, system=SECTION_SYSTEM_PROMPT, method=method)
    if summary_caller is None:
        summary_struct = make_structured(model, LLMNoteSummary, system=SUMMARY_SYSTEM_PROMPT, method=method)

        async def summary_caller(prompt: str) -> str:
            return (await summary_struct(prompt)).summary

    return section_caller, summary_caller


async def _coverage_repair(
    graph: GraphArtifact,
    raw_sections: list[tuple[LLMNoteSection, list[NoteReference]]],
    *,
    section_caller: SectionCaller,
    chunks: list[EvidenceChunk],
    embeddings,
    by_chunk_id: dict[str, EvidenceChunk],
    lecture_title: str,
    topic_pref: str,
    covered_ids: set[str],
    covered_names: list[str],
    max_rounds: int,
    on_section: OnSection | None = None,
) -> None:
    """Detect uncovered core concepts (deterministic) and fill them with bounded LLM passes."""
    core = _core_concepts(graph)
    missing = [concept for concept in core if concept.concept_id not in covered_ids]
    before = len(missing)
    rounds = 0
    while missing and rounds < max_rounds:
        rounds += 1
        batch = missing[:COVERAGE_FILL_BATCH]
        concepts, edges = _topic_subgraph(graph, [concept.concept_id for concept in batch])
        if not concepts:
            break
        grounding = _grounding_chunks(concepts, chunks, embeddings, by_chunk_id)
        position = len(raw_sections) + 1
        prompt = build_section_prompt(
            lecture_title=lecture_title,
            topic_pref=topic_pref,
            section_index=position,
            total_sections=position,
            core_name=concepts[0].name,
            concepts=concepts,
            edges=edges,
            grounding_chunks=grounding,
            covered_concepts=covered_names,
        )
        llm_section = await section_caller(prompt)
        _emit_section(on_section, llm_section)
        raw_sections.append((llm_section, [_reference(chunk) for chunk in grounding]))
        covered_ids.update(concept.concept_id for concept in concepts)
        covered_names.extend(concept.name for concept in concepts)
        missing = [concept for concept in core if concept.concept_id not in covered_ids]
    logger.info(
        "notes coverage critic: %d/%d core concepts uncovered -> %d after %d repair round(s)",
        before, len(core), len(missing), rounds,
    )


def _section_topics(graph: GraphArtifact) -> list[tuple[str, list[str]]]:
    """Decide the section seeds: course core concepts → clusters → top concepts."""
    by_id = {concept.concept_id: concept for concept in graph.concepts}
    if graph.course_meta and graph.course_meta.core_concept_ids:
        return [(by_id[cid].name, [cid]) for cid in graph.course_meta.core_concept_ids if cid in by_id]
    clusters = [
        (cluster.title or "主题", [cid for cid in cluster.concept_ids if cid in by_id])
        for cluster in graph.topic_clusters
    ]
    clusters = [(title, ids) for title, ids in clusters if ids]
    if clusters:
        return clusters
    ranked = sorted(graph.concepts, key=lambda concept: concept.importance_score, reverse=True)
    return [(concept.name, [concept.concept_id]) for concept in ranked[: min(len(ranked), 8)]]


def _core_concepts(graph: GraphArtifact, *, limit: int = CORE_CONCEPT_LIMIT) -> list[ConceptNode]:
    if graph.course_meta and graph.course_meta.core_concept_ids:
        ids = set(graph.course_meta.core_concept_ids)
        return [concept for concept in graph.concepts if concept.concept_id in ids]
    return sorted(graph.concepts, key=lambda concept: concept.importance_score, reverse=True)[:limit]


def _topic_subgraph(
    graph: GraphArtifact,
    concept_ids: list[str],
    *,
    max_concepts: int = SECTION_MAX_CONCEPTS,
    max_neighbors: int = SECTION_MAX_NEIGHBORS,
) -> tuple[list[ConceptNode], list[GraphEdge]]:
    """Concepts in the seed (importance-ranked, capped) + a few neighbors, with internal edges."""
    by_id = {concept.concept_id: concept for concept in graph.concepts}
    seed = sorted(
        (by_id[cid] for cid in concept_ids if cid in by_id),
        key=lambda concept: concept.importance_score,
        reverse=True,
    )
    selected = {concept.concept_id for concept in seed[:max_concepts]}

    adjacency: dict[str, set[str]] = defaultdict(set)
    for edge in graph.edges:
        adjacency[edge.source].add(edge.target)
        adjacency[edge.target].add(edge.source)

    neighbors = [
        by_id[nb]
        for cid in list(selected)
        for nb in adjacency[cid]
        if nb in by_id and nb not in selected
    ]
    neighbors.sort(key=lambda concept: concept.importance_score, reverse=True)
    for concept in neighbors[:max_neighbors]:
        selected.add(concept.concept_id)

    concepts = sorted(
        (by_id[cid] for cid in selected), key=lambda concept: concept.importance_score, reverse=True
    )
    edges = [edge for edge in graph.edges if edge.source in selected and edge.target in selected]
    return concepts, edges


def _grounding_chunks(
    concepts: list[ConceptNode],
    chunks: list[EvidenceChunk],
    embeddings,
    by_chunk_id: dict[str, EvidenceChunk],
    *,
    limit: int = GROUNDING_CHUNK_LIMIT,
) -> list[EvidenceChunk]:
    if not chunks or not concepts:
        return []
    query = " ".join(concept.name for concept in concepts[:4])
    results = search.retrieve_chunks(query, chunks=chunks, embeddings=embeddings, limit=limit)
    return [by_chunk_id[result.ref_id] for result in results if result.ref_id in by_chunk_id]


def _reference(chunk: EvidenceChunk) -> NoteReference:
    return NoteReference(
        source_type=chunk.source_type,
        source_id=chunk.source_id,
        locator=_locator(chunk),
        snippet=chunk.text[:200],
    )


def _locator(chunk: EvidenceChunk) -> str:
    if chunk.page_start is not None:
        return f"第 {chunk.page_start} 页"
    if chunk.time_start is not None:
        return f"{int(chunk.time_start // 60):02d}:{int(chunk.time_start % 60):02d}"
    return ""
