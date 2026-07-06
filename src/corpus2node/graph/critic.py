"""Graph critic: an LLM-judge quality gate over extraction candidates (§4).

It catches what regex can't: definitions with no chunk grounding, reversed/ wrong
relations, and same-entity-different-name duplicates. The judge returns a *typed*
report (it does not rewrite the graph); a deterministic `apply_repair` then prunes
ungrounded concepts, merges duplicates, and flips/retypes/drops bad relations — one
bounded pass, no whole-graph re-extraction. The LLM seam (`acritic`) is injectable
so it runs offline in tests; in production it's bound to Purpose.critic (→ graph).
"""
from __future__ import annotations

import asyncio
import logging
import re
from collections.abc import Awaitable, Callable
from dataclasses import asdict, dataclass

import numpy as np

from corpus2node.core.text import canonicalize_term, normalize_text
from corpus2node.core.types import EvidenceChunk
from corpus2node.graph.clean import VALID_RELATION_TYPES
from corpus2node.graph.schemas import ExtractedConcept, ExtractedRelation, GraphCriticReport

logger = logging.getLogger(__name__)

# acritic(prompt) -> GraphCriticReport — the only LLM-touching seam (mockable in tests).
ACritic = Callable[[str], Awaitable[GraphCriticReport]]

CRITIC_SYSTEM_PROMPT = """\
你是知识图谱质量裁判。你会收到从资料中抽取的概念或关系，请判断其质量问题，只输出结构化裁定，不写解释性长文。
- 概念：定义是否有原文支撑（grounded）；是否与列表中其他概念是同一实体的不同写法（duplicate_of 填它应合并到的 canonical_name，否则留空）。
- 关系：source->target 方向是否正确（错误则 flip=true）；relation_type 是否合适（应改则填 corrected_relation_type，取值范围 is_a/part_of/prerequisite_of/causes/used_for/similar_to）；明显错误或无意义的关系 keep=false。
- 宁可保守：证据不足时保持 grounded=true / keep=true，只在确有问题时标注。
- 只返回 JSON object。
"""


def make_acritic(model, *, method: str = "json_mode") -> ACritic:
    """Bind a chat model to structured GraphCriticReport output (mirrors make_astructured)."""
    from langchain_core.messages import HumanMessage, SystemMessage

    structured = model.with_structured_output(GraphCriticReport, method=method)

    async def _call(prompt: str) -> GraphCriticReport:
        return await structured.ainvoke(
            [SystemMessage(content=CRITIC_SYSTEM_PROMPT), HumanMessage(content=prompt)]
        )

    return _call


async def critique_candidates(
    candidates,
    chunks: list[EvidenceChunk],
    embeddings,
    *,
    acritic: ACritic,
    batch_concepts: int = 40,
    batch_relations: int = 60,
    max_concurrency: int = 8,
) -> GraphCriticReport:
    """Judge concepts (grounding + duplicates) and relations (direction + type), batched + concurrent."""
    concepts: list[ExtractedConcept] = candidates.concepts
    relations: list[ExtractedRelation] = candidates.relations
    if not concepts and not relations:
        return GraphCriticReport()

    all_names = [c.canonical_name for c in concepts]
    def_map = {c.canonical_name: c.definition for c in concepts}
    grounding = _grounding_snippets(concepts, chunks, embeddings) if chunks else {}
    semaphore = asyncio.Semaphore(max(1, max_concurrency))
    errors: list[Exception] = []

    async def judge(prompt: str):
        async with semaphore:
            try:
                return await acritic(prompt)
            except Exception as exc:  # one bad batch must not sink the gate
                logger.exception("critic batch failed")
                errors.append(exc)
                return GraphCriticReport()

    concept_reports = await asyncio.gather(
        *(judge(_concept_prompt(batch, grounding, all_names)) for batch in _batched(concepts, batch_concepts))
    )
    relation_reports = await asyncio.gather(
        *(judge(_relation_prompt(batch, def_map)) for batch in _batched(relations, batch_relations))
    )

    report = GraphCriticReport(
        concept_verdicts=[v for r in concept_reports for v in r.concept_verdicts],
        relation_verdicts=[v for r in relation_reports for v in r.relation_verdicts],
    )
    logger.info(
        "critic: %d concept verdicts, %d relation verdicts (%d/%d batches errored)",
        len(report.concept_verdicts), len(report.relation_verdicts), len(errors),
        len(concept_reports) + len(relation_reports),
    )
    return report


# ── repair (deterministic application of the report) ──────────────────────────


@dataclass
class RepairStats:
    dropped_concepts: int = 0
    merged_concepts: int = 0
    flipped_relations: int = 0
    retyped_relations: int = 0
    dropped_relations: int = 0

    @property
    def total(self) -> int:
        return (
            self.dropped_concepts + self.merged_concepts
            + self.flipped_relations + self.retyped_relations + self.dropped_relations
        )

    def as_dict(self) -> dict:
        return {**asdict(self), "total": self.total}


def apply_repair(candidates, report: GraphCriticReport):
    """Prune ungrounded concepts, merge duplicates, fix relations. Returns (repaired, stats)."""
    from corpus2node.graph.schemas import GraphExtractionResult

    by_name = {c.canonical_name: c for c in candidates.concepts}
    drop: set[str] = set()
    remap: dict[str, str] = {}
    for verdict in report.concept_verdicts:
        name = _resolve_name(verdict.canonical_name, by_name)
        if name is None:
            continue
        if not verdict.grounded:
            drop.add(name)
            continue
        target = verdict.duplicate_of.strip()
        if target and target in by_name and target != name:
            remap[name] = target

    # safety: never let an over-eager judge wipe (or nearly wipe) the graph.
    if _drop_is_too_aggressive(len(by_name), len(drop)):
        logger.warning(
            "critic flagged %d/%d concepts ungrounded — skipping concept drops",
            len(drop), len(by_name),
        )
        drop.clear()

    # don't merge into a target that is itself dropped or remapped (keep it one level)
    remap = {src: tgt for src, tgt in remap.items() if tgt not in drop and tgt not in remap}
    stats = RepairStats(dropped_concepts=len(drop), merged_concepts=len(remap))

    kept: dict[str, ExtractedConcept] = {}
    for concept in candidates.concepts:
        if concept.canonical_name in drop or concept.canonical_name in remap:
            continue
        kept[concept.canonical_name] = concept.model_copy(deep=True)
    for src, tgt in remap.items():
        if tgt in kept and src in by_name:
            source = by_name[src]
            merged = sorted({*kept[tgt].aliases, *source.aliases, source.name, src})
            kept[tgt].aliases = [alias for alias in merged if alias][:10]

    verdict_map = {(v.source_canonical_name, v.target_canonical_name): v for v in report.relation_verdicts}
    new_relations: list[ExtractedRelation] = []
    seen: set[tuple] = set()
    for relation in candidates.relations:
        verdict = verdict_map.get((relation.source_canonical_name, relation.target_canonical_name))
        source = remap.get(relation.source_canonical_name, relation.source_canonical_name)
        target = remap.get(relation.target_canonical_name, relation.target_canonical_name)
        relation_type = relation.relation_type

        if verdict is not None and not verdict.keep:
            stats.dropped_relations += 1
            continue
        if source in drop or target in drop or source not in kept or target not in kept:
            stats.dropped_relations += 1
            continue
        if verdict is not None and verdict.flip:
            source, target = target, source
            stats.flipped_relations += 1
        if verdict is not None and verdict.corrected_relation_type in VALID_RELATION_TYPES:
            relation_type = verdict.corrected_relation_type
            stats.retyped_relations += 1
        if source == target:
            stats.dropped_relations += 1
            continue
        key = (source, target, relation.edge_type, relation_type)
        if key in seen:
            continue
        seen.add(key)
        new_relations.append(
            relation.model_copy(update={"source_canonical_name": source, "target_canonical_name": target, "relation_type": relation_type})
        )

    return GraphExtractionResult(concepts=list(kept.values()), relations=new_relations), stats


# ── helpers ───────────────────────────────────────────────────────────────────


def _resolve_name(name: str, by_name: dict[str, ExtractedConcept]) -> str | None:
    if name in by_name:
        return name
    needle = canonicalize_term(name)
    return next((key for key in by_name if canonicalize_term(key) == needle), None)


def _batched(items: list, size: int) -> list[list]:
    if not items:
        return []
    return [items[i : i + size] for i in range(0, len(items), max(1, size))]


def _grounding_snippets(
    concepts: list[ExtractedConcept], chunks: list[EvidenceChunk], embeddings, *, k: int = 2
) -> dict[str, list[str]]:
    pool = [chunk for chunk in chunks if chunk.embedding]
    if not chunks or not concepts:
        return {}
    indexed = [
        (chunk, chunk.text.lower(), canonicalize_term(chunk.text))
        for chunk in chunks
    ]
    out: dict[str, list[str]] = {}
    for concept in concepts:
        snippets: list[str] = []
        for chunk, lowered, canonical_text in indexed:
            if _chunk_mentions_concept(concept, lowered, canonical_text):
                snippets.append(chunk.text[:200])
                if len(snippets) >= k:
                    break
        if snippets:
            out[concept.canonical_name] = snippets

    if not pool:
        return out

    vectors = embeddings.embed_documents([f"{c.name} {c.definition}".strip() for c in concepts])
    matrix = np.asarray([chunk.embedding for chunk in pool], dtype=float)
    norms = np.linalg.norm(matrix, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    unit = matrix / norms
    for concept, vector in zip(concepts, vectors):
        snippets = out.setdefault(concept.canonical_name, [])
        if len(snippets) >= k:
            continue
        query = np.asarray(vector, dtype=float)
        if query.shape[0] != matrix.shape[1]:
            continue
        query_norm = float(np.linalg.norm(query))
        if query_norm == 0.0:
            continue
        scores = unit @ (query / query_norm)
        order = np.argsort(-scores)[:k]
        seen = set(snippets)
        for i in order:
            if scores[i] <= 0.15:
                continue
            snippet = pool[i].text[:200]
            if snippet in seen:
                continue
            snippets.append(snippet)
            seen.add(snippet)
            if len(snippets) >= k:
                break
    return out


def _concept_prompt(concepts: list[ExtractedConcept], grounding: dict[str, list[str]], all_names: list[str]) -> str:
    lines = [
        "任务：审查下列概念的 grounding 与重复。",
        "",
        "已知全部概念（duplicate_of 必须取自此列表）：",
        "、".join(all_names[:200]),
        "",
        "待审概念：",
    ]
    for concept in concepts:
        parts = [f"canonical_name={concept.canonical_name}", f"name={concept.name}"]
        if concept.definition:
            parts.append(f"definition={concept.definition[:200]}")
        lines.append("- " + " | ".join(parts))
        snippets = grounding.get(concept.canonical_name, [])
        if snippets:
            lines.extend(f"    原文：{snippet}" for snippet in snippets)
        else:
            lines.append("    原文：（检索器未命中；这不是否定证据，除非概念/定义明显不受资料支持，否则保持 grounded=true）")
    lines.extend([
        "",
        '只返回 JSON：{"concept_verdicts":[{"canonical_name":"","grounded":true,"duplicate_of":"","issue":""}],"relation_verdicts":[]}',
    ])
    return "\n".join(lines)


def _drop_is_too_aggressive(total: int, drop_count: int) -> bool:
    if drop_count <= 0 or total <= 0:
        return False
    kept = total - drop_count
    if kept <= 0:
        return True
    if total >= 5 and kept < 2:
        return True
    if total >= 8 and kept < max(3, int(total * 0.2)):
        return True
    return drop_count / total >= 0.85


def _chunk_mentions_concept(concept: ExtractedConcept, lowered: str, canonical_text: str) -> bool:
    for term in _concept_terms(concept):
        if _term_in_text(term, lowered):
            return True
        canonical = canonicalize_term(term)
        if canonical and canonical in canonical_text:
            return True
    return False


def _concept_terms(concept: ExtractedConcept) -> list[str]:
    terms: list[str] = []
    for value in [concept.name, concept.canonical_name, *concept.aliases]:
        normalized = normalize_text(value)
        if normalized:
            terms.append(normalized)
            underscored = normalized.replace("_", " ")
            if underscored != normalized:
                terms.append(underscored)
    return [term for term in dict.fromkeys(terms) if _useful_grounding_term(term)]


def _useful_grounding_term(term: str) -> bool:
    compact = canonicalize_term(term).replace(" ", "")
    if not compact:
        return False
    ascii_only = all(ord(char) < 128 for char in compact)
    return len(compact) >= (3 if ascii_only else 2)


def _term_in_text(term: str, lowered: str) -> bool:
    needle = term.lower()
    if all(ord(char) < 128 for char in needle):
        return re.search(rf"(?<![A-Za-z0-9_]){re.escape(needle)}(?![A-Za-z0-9_])", lowered) is not None
    return needle in lowered


def _relation_prompt(relations: list[ExtractedRelation], def_map: dict[str, str]) -> str:
    involved = {name for relation in relations for name in (relation.source_canonical_name, relation.target_canonical_name)}
    lines = ["任务：审查下列关系的方向与类型。", "", "概念定义参考："]
    for name in sorted(involved):
        definition = def_map.get(name, "")
        lines.append(f"- {name}: {definition[:120]}")
    lines.extend(["", "待审关系（source -> target，relation_type）："])
    for relation in relations:
        lines.append(f"- {relation.source_canonical_name} -> {relation.target_canonical_name} ({relation.relation_type or relation.edge_type})")
    lines.extend([
        "",
        "relation_type 取值：is_a/part_of/prerequisite_of/causes/used_for/similar_to。",
        '只返回 JSON：{"concept_verdicts":[],"relation_verdicts":[{"source_canonical_name":"","target_canonical_name":"","keep":true,"flip":false,"corrected_relation_type":"","issue":""}]}',
    ])
    return "\n".join(lines)
