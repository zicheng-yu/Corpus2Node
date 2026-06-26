from __future__ import annotations

import asyncio
import itertools
import random
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

import numpy as np
from pydantic import BaseModel, Field, field_validator

from corpus2node.core.types import (
    ConceptNode,
    CourseSession,
    DiscoveryBridgeEdge,
    DiscoveryBridgeGraph,
    DiscoveryBridgeNode,
    DiscoveryEvidence,
    DiscoveryFinding,
    DiscoveryMode,
    DiscoveryParticipant,
    DiscoveryReport,
    DiscoveryRequest,
    EvidenceChunk,
    GraphArtifact,
)
from corpus2node.llm import factory
from corpus2node.llm.credentials import Purpose
from corpus2node.llm.structured import StructuredCaller, make_structured
from corpus2node.storage import local

# Canonical relation vocabulary. The frontend label table mirrors these exactly,
# so constraining the judge here keeps every finding renderable. Order matters
# only for documentation/prompting.
RELATION_TYPES: tuple[str, ...] = (
    "same_under_different_terms",
    "prerequisite",
    "complement",
    "analogy",
    "method_to_application",
    "contradiction",
    "shared_context",
    "open_question",
)
_RELATION_SET = set(RELATION_TYPES)

# The judge sometimes answers with a Chinese label instead of the enum key; map
# the common ones back so a good finding is not silently downgraded.
_CN_RELATION_ALIASES: dict[str, str] = {
    "异名同义": "same_under_different_terms",
    "同义": "same_under_different_terms",
    "前置依赖": "prerequisite",
    "前置": "prerequisite",
    "依赖": "prerequisite",
    "互补": "complement",
    "类比": "analogy",
    "方法迁移": "method_to_application",
    "迁移": "method_to_application",
    "矛盾张力": "contradiction",
    "矛盾": "contradiction",
    "共同场景": "shared_context",
    "场景": "shared_context",
    "待探索问题": "open_question",
    "开放问题": "open_question",
    "开放性问题": "open_question",
}

# Above this many pooled candidates the judge prompt is split into batches and
# judged concurrently, so a large selection neither blows the context window nor
# serialises into one slow call.
_JUDGE_BATCH = 12


class DiscoveryInputError(ValueError):
    """Raised for user-fixable discovery input problems."""


class JudgedFinding(BaseModel):
    candidate_id: str
    keep: bool = True
    title: str = ""
    summary: str = ""
    relation_type: str = "shared_context"
    reasoning: str = ""
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    novelty: float = Field(default=0.0, ge=0.0, le=1.0)

    @field_validator("relation_type", mode="before")
    @classmethod
    def _coerce_relation(cls, value: Any) -> str:
        if not isinstance(value, str):
            return "shared_context"
        key = value.strip().lower()
        if key in _RELATION_SET:
            return key
        return _CN_RELATION_ALIASES.get(value.strip(), "shared_context")


class JudgeReport(BaseModel):
    findings: list[JudgedFinding] = Field(default_factory=list)


class DiscoveryTitle(BaseModel):
    title: str = ""


DiscoveryJudge = Callable[[str], Awaitable[JudgeReport]]
DiscoveryTitler = Callable[[str], Awaitable[str]]
_AUTO_JUDGE = object()
_AUTO_TITLER = object()


@dataclass(frozen=True)
class DiscoveryContext:
    session: CourseSession
    graph: GraphArtifact
    chunks: list[EvidenceChunk]


@dataclass(frozen=True)
class ConceptRecord:
    context: DiscoveryContext
    concept: ConceptNode


@dataclass(frozen=True)
class Candidate:
    candidate_id: str
    left: ConceptRecord
    right: ConceptRecord
    score: float
    similarity: float
    lexical_overlap: float
    structural: float
    importance: float
    cross_session: bool
    method_link: bool
    evidence: list[DiscoveryEvidence]


async def run_discovery(
    request: DiscoveryRequest,
    *,
    judge: DiscoveryJudge | None | object = _AUTO_JUDGE,
    titler: DiscoveryTitler | None | object = _AUTO_TITLER,
) -> DiscoveryReport:
    """Create a persisted-ready discovery report from selected or random sessions.

    The first stage intentionally uses broad deterministic recall (similarity,
    lexical, structural and graph-importance signals). If an LLM judge is
    available, it decides which broad candidates are real knowledge crossings;
    otherwise deterministic findings are still returned so the feature remains
    useful without credentials. An LLM titler names the report (with a
    deterministic fallback), so history shows a readable title not a uuid.
    """
    rng = random.Random(request.seed)
    contexts = _load_contexts(request, rng)
    if titler is _AUTO_TITLER:
        titler = _make_titler_or_none()
    candidates = _generate_candidates(contexts, request, rng)
    if not candidates:
        return DiscoveryReport(
            title=_fallback_title([], contexts),
            mode=request.mode,
            session_ids=[ctx.session.session_id for ctx in contexts],
        )

    judged: list[JudgedFinding] = []
    if judge is _AUTO_JUDGE:
        judge = _make_judge_or_none()
    if judge is not None:
        judged = await _run_judge(judge, candidates, request.limit)

    findings = _findings_from_judgement(candidates, judged, request.limit)
    if not findings:
        findings = [_finding_from_candidate(candidate) for candidate in candidates[: request.limit]]

    capped = findings[: request.limit]
    title = await _title_for(capped, contexts, titler)
    return DiscoveryReport(
        title=title,
        mode=request.mode,
        session_ids=[ctx.session.session_id for ctx in contexts],
        findings=capped,
        bridge_graph=_bridge_graph(capped),
    )


async def _run_judge(judge: DiscoveryJudge, candidates: list[Candidate], limit: int) -> list[JudgedFinding]:
    """Judge the candidate pool, batching + parallelising when it is large."""
    batches = [candidates[i : i + _JUDGE_BATCH] for i in range(0, len(candidates), _JUDGE_BATCH)]
    if len(batches) == 1:
        try:
            return (await judge(_judge_prompt(batches[0], limit))).findings
        except Exception:
            return []

    results = await asyncio.gather(
        *(judge(_judge_prompt(batch, limit)) for batch in batches),
        return_exceptions=True,
    )
    judged: list[JudgedFinding] = []
    for result in results:
        if isinstance(result, JudgeReport):
            judged.extend(result.findings)
    return judged


def _load_contexts(request: DiscoveryRequest, rng: random.Random) -> list[DiscoveryContext]:
    session_ids = list(dict.fromkeys(request.session_ids))
    if request.mode == DiscoveryMode.random and not session_ids:
        session_ids = _random_session_ids(rng)
    if request.mode == DiscoveryMode.selected and not session_ids:
        raise DiscoveryInputError("Select at least one built session for knowledge discovery.")
    if not session_ids:
        raise DiscoveryInputError("No built sessions are available for random discovery.")

    contexts: list[DiscoveryContext] = []
    for session_id in session_ids:
        try:
            session = local.load_session(session_id)
            graph = local.load_graph_artifact(session_id)
        except FileNotFoundError as exc:
            raise DiscoveryInputError(f"Session {session_id} has no built graph.") from exc
        if session.lecture_title.startswith(local.COURSE_GRAPH_LECTURE_PREFIX):
            continue
        chunks = [chunk for artifact in local.list_ingest_artifacts(session_id) for chunk in artifact.chunks]
        if graph.concepts:
            contexts.append(DiscoveryContext(session=session, graph=graph, chunks=chunks))

    if not contexts:
        raise DiscoveryInputError("No selectable sessions with graph concepts were found.")
    return contexts


def _random_session_ids(rng: random.Random, *, max_sessions: int = 5) -> list[Any]:
    ids = []
    for session_id in local.list_session_ids():
        try:
            session = local.load_session(session_id)
            graph = local.load_graph_artifact(session_id)
        except FileNotFoundError:
            continue
        if session.lecture_title.startswith(local.COURSE_GRAPH_LECTURE_PREFIX) or not graph.concepts:
            continue
        ids.append(session_id)
    rng.shuffle(ids)
    return ids[:max_sessions]


def _generate_candidates(
    contexts: list[DiscoveryContext], request: DiscoveryRequest, rng: random.Random
) -> list[Candidate]:
    records = list(itertools.chain.from_iterable(_records_for_context(ctx, request) for ctx in contexts))
    if len(records) < 2:
        return []

    neighbor_index = _neighbor_index(contexts)

    pairs: list[tuple[ConceptRecord, ConceptRecord]]
    if len(contexts) == 1:
        pairs = list(itertools.combinations(records, 2))
    else:
        pairs = [
            (a, b)
            for a, b in itertools.combinations(records, 2)
            if a.context.session.session_id != b.context.session.session_id
        ]

    candidates: list[Candidate] = []
    for index, (left, right) in enumerate(pairs, start=1):
        evidence = _interleave(_evidence_for(left), _evidence_for(right))[:4]
        similarity = _cosine(left.concept.embedding, right.concept.embedding)
        lexical = _lexical_overlap(_concept_terms(left.concept), _concept_terms(right.concept))
        structural = _lexical_overlap(
            _struct_terms(left.concept) | neighbor_index.get(_record_key(left), set()),
            _struct_terms(right.concept) | neighbor_index.get(_record_key(right), set()),
        )
        importance = min(1.0, (left.concept.importance_score + right.concept.importance_score) / 2.0)
        norm_similarity = (similarity + 1.0) / 2.0 if similarity else 0.0
        evidence_strength = min(1.0, len(evidence) / 3.0)
        score = (
            0.34 * norm_similarity
            + 0.16 * lexical
            + 0.14 * structural
            + 0.20 * importance
            + 0.16 * evidence_strength
        )
        candidates.append(
            Candidate(
                candidate_id=f"cand-{index}",
                left=left,
                right=right,
                score=round(score, 4),
                similarity=round(similarity, 4),
                lexical_overlap=round(lexical, 4),
                structural=round(structural, 4),
                importance=round(importance, 4),
                cross_session=left.context.session.session_id != right.context.session.session_id,
                method_link=_method_link(left.concept, right.concept),
                evidence=evidence,
            )
        )

    ranked = sorted(candidates, key=lambda c: c.score, reverse=True)
    pool_size = max(request.limit * 4, 24)
    if request.mode == DiscoveryMode.random:
        diverse = sorted(candidates, key=lambda c: 0.55 * c.score + 0.45 * rng.random(), reverse=True)
        return _dedup_candidates([*diverse[:pool_size], *ranked[: request.limit]])[:pool_size]
    return _dedup_candidates([*ranked[:pool_size], *_random_tail(candidates, rng, request.limit)])[:pool_size]


def _records_for_context(ctx: DiscoveryContext, request: DiscoveryRequest, *, max_concepts: int = 18) -> list[ConceptRecord]:
    focus = set(request.focus_concept_ids.get(str(ctx.session.session_id), []))
    concepts = ctx.graph.concepts
    if focus:
        concepts = [concept for concept in concepts if concept.concept_id in focus]
    concepts = sorted(concepts, key=lambda c: c.importance_score, reverse=True)[:max_concepts]
    return [ConceptRecord(context=ctx, concept=concept) for concept in concepts]


def _neighbor_index(contexts: list[DiscoveryContext]) -> dict[tuple[str, str], set[str]]:
    """Map each (session, concept) to the canonical names of its graph neighbours.

    Two concepts that share neighbours (even with different names) are structurally
    related, which the LLM-free scoring can otherwise miss.
    """
    index: dict[tuple[str, str], set[str]] = {}
    for ctx in contexts:
        session_key = str(ctx.session.session_id)
        names = {c.concept_id: (c.canonical_name or c.name).lower() for c in ctx.graph.concepts}
        for edge in ctx.graph.edges:
            src, dst = edge.source, edge.target
            if src in names and dst in names:
                index.setdefault((session_key, src), set()).add(names[dst])
                index.setdefault((session_key, dst), set()).add(names[src])
    return index


def _record_key(record: ConceptRecord) -> tuple[str, str]:
    return (str(record.context.session.session_id), record.concept.concept_id)


def _interleave(left: list[DiscoveryEvidence], right: list[DiscoveryEvidence]) -> list[DiscoveryEvidence]:
    """Alternate evidence from both sides so the first items represent both."""
    out: list[DiscoveryEvidence] = []
    for a, b in itertools.zip_longest(left, right):
        if a is not None:
            out.append(a)
        if b is not None:
            out.append(b)
    return out


def _random_tail(candidates: list[Candidate], rng: random.Random, limit: int) -> list[Candidate]:
    pool = candidates[:]
    rng.shuffle(pool)
    return pool[: max(4, limit)]


def _dedup_candidates(candidates: list[Candidate]) -> list[Candidate]:
    seen: set[tuple[str, str, str, str]] = set()
    out: list[Candidate] = []
    for candidate in candidates:
        left_key = (str(candidate.left.context.session.session_id), candidate.left.concept.concept_id)
        right_key = (str(candidate.right.context.session.session_id), candidate.right.concept.concept_id)
        key = (*left_key, *right_key) if left_key <= right_key else (*right_key, *left_key)
        if key in seen:
            continue
        seen.add(key)
        out.append(candidate)
    return out


def _make_judge_or_none() -> StructuredCaller[JudgeReport] | None:
    try:
        model = factory.build_chat_model(Purpose.critic, temperature=0)
        method = factory.structured_output_method(Purpose.critic)
    except Exception:
        return None
    return make_structured(model, JudgeReport, system=_JUDGE_SYSTEM, method=method)


_TITLE_SYSTEM = (
    "你是为跨资料知识发现起标题的助手。只输出一个简短中文标题（不超过 16 字），"
    "概括这次发现的主题；不要书名号、引号或句末标点。"
)


def _make_titler_or_none() -> DiscoveryTitler | None:
    try:
        model = factory.build_chat_model(Purpose.critic, temperature=0)
        method = factory.structured_output_method(Purpose.critic)
    except Exception:
        return None
    caller = make_structured(model, DiscoveryTitle, system=_TITLE_SYSTEM, method=method)

    async def _titler(prompt: str) -> str:
        return (await caller(prompt)).title

    return _titler


def _title_prompt(findings: list[DiscoveryFinding], contexts: list[DiscoveryContext]) -> str:
    lectures = list(dict.fromkeys(ctx.session.lecture_title for ctx in contexts))
    return "\n".join(
        [
            "给下面这次跨资料知识发现起一个简短中文标题（≤16 字，概括主题）。",
            "涉及资料：" + "、".join(lectures[:6]),
            "主要发现：",
            *[f"- {f.title}" for f in findings[:6]],
        ]
    )


async def _title_for(
    findings: list[DiscoveryFinding], contexts: list[DiscoveryContext], titler: DiscoveryTitler | None
) -> str:
    if titler is not None and findings:
        try:
            raw = await titler(_title_prompt(findings, contexts))
            cleaned = (raw or "").strip().strip("《》「」\"'。.！!？? ")
            if cleaned:
                return cleaned[:24]
        except Exception:
            pass
    return _fallback_title(findings, contexts)


def _clean_concept_name(name: str) -> str:
    """Drop parenthetical suffixes and surrounding noise so titles read cleanly."""
    name = name.split("(")[0].split("（")[0].strip()
    return name.strip(" -·:：")


def derive_title(findings: list[DiscoveryFinding]) -> str:
    """Deterministic title from the top finding's participants (no LLM)."""
    if not findings:
        return ""
    top = findings[0]
    names = [n for n in (_clean_concept_name(p.concept_name) for p in top.participants) if n][:2]
    if len(names) >= 2:
        base = f"{names[0]} × {names[1]}"
    elif names:
        base = names[0]
    else:
        base = _clean_concept_name(top.title) or "知识发现"
    extra = f" 等 {len(findings)} 处" if len(findings) > 1 else ""
    title = (base + extra).strip()
    if len(title) > 24:  # avoid a dangling separator after truncation
        title = title[:24].rstrip(" ×（(·-、")
    return title


def _fallback_title(findings: list[DiscoveryFinding], contexts: list[DiscoveryContext]) -> str:
    title = derive_title(findings)
    if title:
        return title
    lectures = list(dict.fromkeys(ctx.session.lecture_title for ctx in contexts))
    if lectures:
        return ("、".join(lectures[:2]) + " 的发现")[:24]
    return "知识发现"


_RELATION_GUIDE = (
    "same_under_different_terms=异名同义, prerequisite=前置依赖, complement=互补, "
    "analogy=类比, method_to_application=方法迁移, contradiction=矛盾张力, "
    "shared_context=共同场景, open_question=待探索问题"
)

_JUDGE_SYSTEM = f"""你是知识发现裁判。你的任务不是找同名词，而是判断不同资料里的知识是否存在可解释交叉。
只保留有证据支撑的发现；可以识别互补、类比、前置依赖、方法迁移、矛盾张力、共同场景和开放问题。
relation_type 只能取以下英文枚举之一：{_RELATION_GUIDE}。
输出 JSON，candidate_id 必须来自候选；如果候选没有真实交叉，keep=false 或不要返回。"""


def _judge_prompt(candidates: list[Candidate], limit: int) -> str:
    lines = [
        f"请从下面候选中选出最多 {limit} 条真正有知识发现价值的交叉点。",
        "不要只看术语是否相同；重点判断是否存在可迁移的方法、共同问题、互补前提或可比较结构。",
        "每条发现必须能被候选中的两个资料证据支撑。",
        f"relation_type 必须取自：{_RELATION_GUIDE}。",
        "",
    ]
    for candidate in candidates:
        lines.extend(
            [
                f"候选 {candidate.candidate_id}｜算法分 {candidate.score:.2f}｜向量相似 {candidate.similarity:.2f}"
                f"｜词面 {candidate.lexical_overlap:.2f}｜结构 {candidate.structural:.2f}",
                _participant_line("A", candidate.left),
                _participant_line("B", candidate.right),
                "证据：",
                *[f"- {ev.lecture_title} / {ev.concept_name}: {ev.snippet}" for ev in candidate.evidence[:4]],
                "",
            ]
        )
    return "\n".join(lines)


def _participant_line(label: str, record: ConceptRecord) -> str:
    concept = record.concept
    return (
        f"{label}: {record.context.session.course_title} / {record.context.session.lecture_title} / "
        f"{concept.name}：{concept.summary or concept.definition}"
    )


def _findings_from_judgement(
    candidates: list[Candidate], judged: list[JudgedFinding], limit: int
) -> list[DiscoveryFinding]:
    by_id = {candidate.candidate_id: candidate for candidate in candidates}
    findings: list[DiscoveryFinding] = []
    seen: set[str] = set()
    # Strongest crossings first — important once batches are merged.
    for item in sorted(judged, key=lambda i: i.confidence, reverse=True):
        if not item.keep or item.candidate_id not in by_id or item.candidate_id in seen:
            continue
        seen.add(item.candidate_id)
        findings.append(_finding_from_candidate(by_id[item.candidate_id], judged=item))
        if len(findings) >= limit:
            break
    return findings


def _finding_from_candidate(candidate: Candidate, judged: JudgedFinding | None = None) -> DiscoveryFinding:
    left = candidate.left
    right = candidate.right
    title = judged.title if judged and judged.title else f"{left.concept.name} ↔ {right.concept.name}"
    summary = judged.summary if judged and judged.summary else _default_summary(candidate)
    reasoning = judged.reasoning if judged and judged.reasoning else "由概念描述、资料证据、共享结构和图谱重要性共同提示这两个知识点可能存在交叉。"
    return DiscoveryFinding(
        title=title,
        summary=summary,
        relation_type=(judged.relation_type if judged else _relation_type_for(candidate)),
        confidence=round((judged.confidence if judged else min(0.95, candidate.score)), 4),
        novelty=round((judged.novelty if judged else _novelty_for(candidate)), 4),
        participants=[_participant(left), _participant(right)],
        evidence=candidate.evidence,
        reasoning=reasoning,
        score_components={
            "candidate_score": candidate.score,
            "similarity": candidate.similarity,
            "lexical_overlap": candidate.lexical_overlap,
            "structural": candidate.structural,
            "importance": candidate.importance,
        },
    )


def _default_summary(candidate: Candidate) -> str:
    left, right = candidate.left.concept, candidate.right.concept
    return (
        f"{left.name} 与 {right.name} 未必是同名知识点，但它们的定义、应用或证据片段显示出可比较的结构，"
        "适合作为进一步追问或复习串联。"
    )


def _relation_type_for(candidate: Candidate) -> str:
    if candidate.method_link:
        return "method_to_application"
    if candidate.lexical_overlap >= 0.5 and candidate.similarity >= 0.55:
        return "same_under_different_terms"
    if candidate.structural >= 0.3 and candidate.lexical_overlap < 0.2:
        return "complement"
    if candidate.similarity >= 0.62:
        return "analogy"
    if candidate.lexical_overlap >= 0.22 or candidate.structural >= 0.2:
        return "shared_context"
    return "open_question"


def _novelty_for(candidate: Candidate) -> float:
    norm_similarity = (candidate.similarity + 1.0) / 2.0 if candidate.similarity else 0.0
    cross = 1.0 if candidate.cross_session else 0.0
    value = 0.5 * (1.0 - norm_similarity) + 0.3 * (1.0 - candidate.lexical_overlap) + 0.2 * cross
    return max(0.1, min(1.0, value))


def _method_link(left: ConceptNode, right: ConceptNode) -> bool:
    left_apps = " ".join(left.applications).lower()
    right_apps = " ".join(right.applications).lower()
    left_names = [name.lower() for name in [left.name, left.canonical_name] if name]
    right_names = [name.lower() for name in [right.name, right.canonical_name] if name]
    return any(name in right_apps for name in left_names) or any(name in left_apps for name in right_names)


def _participant(record: ConceptRecord) -> DiscoveryParticipant:
    return DiscoveryParticipant(
        session_id=record.context.session.session_id,
        course_title=record.context.session.course_title,
        lecture_title=record.context.session.lecture_title,
        concept_id=record.concept.concept_id,
        concept_name=record.concept.name,
        summary=record.concept.summary or record.concept.definition,
    )


def _evidence_for(record: ConceptRecord, *, top_k: int = 2) -> list[DiscoveryEvidence]:
    concept = record.concept
    terms = [term.lower() for term in [concept.name, concept.canonical_name, *concept.aliases] if term]
    scored: list[tuple[float, EvidenceChunk]] = []
    for chunk in record.context.chunks:
        text = chunk.text.lower()
        lexical = 1.0 if any(term and term in text for term in terms) else 0.0
        semantic = _cosine(concept.embedding, chunk.embedding)
        scored.append((lexical + max(0.0, semantic), chunk))
    scored.sort(key=lambda item: item[0], reverse=True)
    picked = [chunk for value, chunk in scored[:top_k] if value > 0]
    if picked:
        return [_chunk_evidence(record, chunk) for chunk in picked]
    snippet = concept.summary or concept.definition or concept.name
    return [
        DiscoveryEvidence(
            session_id=record.context.session.session_id,
            course_title=record.context.session.course_title,
            lecture_title=record.context.session.lecture_title,
            concept_id=concept.concept_id,
            concept_name=concept.name,
            snippet=snippet[:220],
        )
    ]


def _chunk_evidence(record: ConceptRecord, chunk: EvidenceChunk) -> DiscoveryEvidence:
    return DiscoveryEvidence(
        session_id=record.context.session.session_id,
        course_title=record.context.session.course_title,
        lecture_title=record.context.session.lecture_title,
        concept_id=record.concept.concept_id,
        concept_name=record.concept.name,
        chunk_id=chunk.chunk_id,
        source_id=chunk.source_id,
        source_type=chunk.source_type,
        locator=_locator(chunk),
        snippet=chunk.text[:220],
    )


def _bridge_graph(findings: list[DiscoveryFinding]) -> DiscoveryBridgeGraph:
    nodes: dict[str, DiscoveryBridgeNode] = {}
    edges: dict[tuple[str, str, str], DiscoveryBridgeEdge] = {}
    for finding in findings:
        finding_id = f"finding:{finding.finding_id}"
        nodes[finding_id] = DiscoveryBridgeNode(
            id=finding_id,
            label=finding.title,
            node_type="finding",
            metadata={"relation_type": finding.relation_type, "confidence": finding.confidence},
        )
        for participant in finding.participants:
            session_node = f"session:{participant.session_id}"
            concept_node = f"concept:{participant.session_id}:{participant.concept_id}"
            nodes.setdefault(
                session_node,
                DiscoveryBridgeNode(
                    id=session_node,
                    label=participant.lecture_title,
                    node_type="session",
                    session_id=participant.session_id,
                    metadata={"course_title": participant.course_title},
                ),
            )
            nodes.setdefault(
                concept_node,
                DiscoveryBridgeNode(
                    id=concept_node,
                    label=participant.concept_name,
                    node_type="concept",
                    session_id=participant.session_id,
                    metadata={"concept_id": participant.concept_id},
                ),
            )
            edges[(concept_node, session_node, "from_session")] = DiscoveryBridgeEdge(
                source=concept_node, target=session_node, edge_type="from_session", weight=1.0
            )
            edges[(finding_id, concept_node, finding.relation_type)] = DiscoveryBridgeEdge(
                source=finding_id,
                target=concept_node,
                edge_type=finding.relation_type,
                weight=finding.confidence,
            )
    return DiscoveryBridgeGraph(nodes=list(nodes.values()), edges=list(edges.values()))


def _concept_terms(concept: ConceptNode) -> set[str]:
    raw = " ".join(
        [
            concept.name,
            concept.canonical_name,
            concept.summary,
            concept.definition,
            " ".join(concept.tags),
            " ".join(concept.applications),
            " ".join(concept.prerequisites),
        ]
    ).lower()
    return {token.strip("，。,.；;：:（）()[]【】 ") for token in raw.split() if len(token.strip()) >= 2}


def _struct_terms(concept: ConceptNode) -> set[str]:
    """Structural vocabulary: tags / applications / prerequisites only."""
    raw = " ".join([" ".join(concept.tags), " ".join(concept.applications), " ".join(concept.prerequisites)]).lower()
    return {token.strip("，。,.；;：:（）()[]【】 ") for token in raw.split() if len(token.strip()) >= 2}


def _lexical_overlap(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def _cosine(left: list[float], right: list[float]) -> float:
    if not left or not right or len(left) != len(right):
        return 0.0
    a = np.asarray(left, dtype=float)
    b = np.asarray(right, dtype=float)
    denom = float(np.linalg.norm(a) * np.linalg.norm(b))
    if denom == 0:
        return 0.0
    return float(a @ b / denom)


def _locator(chunk: EvidenceChunk) -> str:
    if chunk.page_start is not None:
        return f"第 {chunk.page_start} 页"
    if chunk.time_start is not None:
        return f"{int(chunk.time_start // 60):02d}:{int(chunk.time_start % 60):02d}"
    return ""
