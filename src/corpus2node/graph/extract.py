"""LLM graph extraction: concurrent, full-coverage, structured-output.

Rewritten vs. the donor:
- B: extracts from ALL chunks (donor stride-sampled down to 64 — silently lossy).
- structured output via with_structured_output (donor hand-parsed JSON).
- concurrency via asyncio.Semaphore over async ainvoke (donor used a thread pool).
Tuned cleaning/normalization/merge logic is kept.
"""
from __future__ import annotations

import asyncio
import logging
import re
from collections.abc import Awaitable, Callable

from corpus2node.core.types import EdgeType, EvidenceChunk
from corpus2node.graph.clean import VALID_RELATION_TYPES, looks_like_noise
from corpus2node.graph.prompts import GRAPH_SYSTEM_PROMPT, build_graph_prompt, chunk_prompt_text
from corpus2node.graph.schemas import ExtractedConcept, ExtractedRelation, GraphExtractionResult
from corpus2node.core.text import canonicalize_term, normalize_text

logger = logging.getLogger(__name__)

# astructured(prompt) -> GraphExtractionResult — the only LLM-touching seam (mockable in tests).
AStructured = Callable[[str], Awaitable[GraphExtractionResult]]


def make_astructured(model) -> AStructured:
    """Bind a LangChain chat model to structured GraphExtractionResult output."""
    from langchain_core.messages import HumanMessage, SystemMessage

    # function_calling is the most broadly supported across OpenAI-compatible
    # vendors (DeepSeek/Kimi/etc.); strict json_schema is OpenAI-specific.
    structured = model.with_structured_output(GraphExtractionResult, method="function_calling")

    async def _call(prompt: str) -> GraphExtractionResult:
        return await structured.ainvoke(
            [SystemMessage(content=GRAPH_SYSTEM_PROMPT), HumanMessage(content=prompt)]
        )

    return _call


async def extract_graph_candidates(
    chunks: list[EvidenceChunk],
    *,
    astructured: AStructured,
    max_concurrency: int = 8,
    batch_max_chars: int = 5200,
    batch_max_chunks: int = 8,
) -> GraphExtractionResult:
    """Extract concepts/relations from every usable chunk, batched and run concurrently."""
    usable = [chunk for chunk in chunks if not is_low_signal_chunk(chunk)] or list(chunks)
    batches = chunk_batches(usable, max_chars=batch_max_chars, max_chunks=batch_max_chunks)
    if not batches:
        return GraphExtractionResult()

    semaphore = asyncio.Semaphore(max(1, max_concurrency))
    errors: list[Exception] = []

    async def run(batch: list[EvidenceChunk]) -> GraphExtractionResult | None:
        async with semaphore:
            try:
                return await astructured(build_graph_prompt(batch))
            except Exception as exc:  # one bad batch must not sink the whole extraction
                logger.exception("graph extraction batch failed (%d chunks)", len(batch))
                errors.append(exc)
                return None

    logger.info("extracting graph from %d chunks in %d batches", len(usable), len(batches))
    results = await asyncio.gather(*(run(batch) for batch in batches))
    collected = [result for result in results if result is not None]
    if not collected and errors:
        # every batch errored — surface the real cause instead of a vague downstream failure
        raise RuntimeError(
            f"all {len(batches)} extraction batches failed; last error: "
            f"{type(errors[-1]).__name__}: {errors[-1]}"
        )
    merged = merge_results(collected)
    logger.info(
        "extract merged: %d concepts, %d relations (%d/%d batches ok)",
        len(merged.concepts), len(merged.relations), len(collected), len(batches),
    )
    return merged


def chunk_batches(
    chunks: list[EvidenceChunk], *, max_chars: int, max_chunks: int
) -> list[list[EvidenceChunk]]:
    batches: list[list[EvidenceChunk]] = []
    current: list[EvidenceChunk] = []
    current_chars = 0
    for chunk in chunks:
        text = chunk_prompt_text(chunk)
        if not text:
            continue
        cost = len(text) + len(chunk.chunk_id) + 24
        if current and (current_chars + cost > max_chars or len(current) >= max_chunks):
            batches.append(current)
            current, current_chars = [], 0
        current.append(chunk)
        current_chars += cost
    if current:
        batches.append(current)
    return batches


def merge_results(results: list[GraphExtractionResult]) -> GraphExtractionResult:
    concept_map: dict[str, ExtractedConcept] = {}
    relation_map: dict[tuple[str, str, str, str | None], ExtractedRelation] = {}

    for result in results:
        for concept in result.concepts:
            normalized = normalize_concept(concept)
            if normalized is None:
                continue
            existing = concept_map.get(normalized.canonical_name)
            if existing is None:
                concept_map[normalized.canonical_name] = normalized
                continue
            existing.aliases = sorted(
                {*existing.aliases, *normalized.aliases, existing.name, normalized.name}
            )[:10]
            if len(normalized.definition) > len(existing.definition):
                existing.definition = normalized.definition
            if len(normalized.name) > len(existing.name):
                existing.name = normalized.name

        for relation in result.relations:
            normalized_rel = normalize_relation(relation)
            if normalized_rel is None:
                continue
            key = (
                normalized_rel.source_canonical_name,
                normalized_rel.target_canonical_name,
                normalized_rel.edge_type,
                normalized_rel.relation_type,
            )
            existing_rel = relation_map.get(key)
            if existing_rel is None:
                relation_map[key] = normalized_rel
            else:
                existing_rel.confidence = round(max(existing_rel.confidence, normalized_rel.confidence), 3)

    return GraphExtractionResult(
        concepts=sorted(concept_map.values(), key=lambda item: item.name),
        relations=list(relation_map.values()),
    )


def normalize_concept(concept: ExtractedConcept) -> ExtractedConcept | None:
    name = normalize_text(concept.name)
    canonical_name = canonicalize_term(concept.canonical_name or name)
    if not canonical_name or looks_like_noise(canonical_name):
        return None

    aliases: list[str] = []
    for alias in [name, canonical_name, *concept.aliases]:
        cleaned = normalize_text(alias)
        if cleaned and not looks_like_noise(canonicalize_term(cleaned)):
            aliases.append(cleaned)
    deduped = list(dict.fromkeys(aliases)) or [name]

    return ExtractedConcept(
        name=name or deduped[0],
        canonical_name=canonical_name,
        aliases=deduped[:10],
        definition=normalize_text(concept.definition),
        summary=normalize_text(concept.summary),
        key_points=_clean_short_lines(concept.key_points, max_items=4),
        tags=_clean_short_lines(concept.tags, max_items=5),
        prerequisites=_clean_short_lines(concept.prerequisites, max_items=4),
        applications=_clean_short_lines(concept.applications, max_items=4),
    )


def normalize_relation(relation: ExtractedRelation) -> ExtractedRelation | None:
    source = canonicalize_term(relation.source_canonical_name)
    target = canonicalize_term(relation.target_canonical_name)
    if not source or not target or source == target:
        return None
    if looks_like_noise(source) or looks_like_noise(target):
        return None

    valid_edges = {item.value for item in EdgeType}
    edge_type = relation.edge_type if relation.edge_type in valid_edges else EdgeType.relates_to.value
    relation_type = normalize_text(relation.relation_type or "") or None
    if edge_type == EdgeType.relates_to.value:
        if relation_type not in VALID_RELATION_TYPES:
            return None
    else:
        relation_type = None

    return ExtractedRelation(
        source_canonical_name=source,
        target_canonical_name=target,
        edge_type=edge_type,
        relation_type=relation_type,
        confidence=max(0.0, min(float(relation.confidence), 1.0)),
    )


def _clean_short_lines(items: list[str], *, max_items: int) -> list[str]:
    cleaned: list[str] = []
    seen: set[str] = set()
    for item in items:
        value = normalize_text(item)
        if not value or value.lower() in seen:
            continue
        seen.add(value.lower())
        cleaned.append(value[:120])
        if len(cleaned) >= max_items:
            break
    return cleaned


def is_low_signal_chunk(chunk: EvidenceChunk) -> bool:
    text = normalize_text(chunk.text)
    lowered = text.lower()
    if chunk.source_type.value == "audio" and lowered.startswith("asr failed for "):
        return True
    if len(text) < 24:
        return True
    if any(token in lowered for token in {"learning objective", "授课大纲", "学习目标", "课堂纪律"}):
        return True
    if re.fullmatch(r"[\d\.\s\-:：a-zA-Z一二三四五六七八九十]+", text) and len(text) < 80:
        return True
    return False
