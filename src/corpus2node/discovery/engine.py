from __future__ import annotations

import asyncio
import itertools
import logging
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
    InnovationProposal,
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


logger = logging.getLogger(__name__)


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


class ProposedIdea(BaseModel):
    """One LLM-drafted innovation idea; concept_names must reference finding concepts."""

    title: str = ""
    pitch: str = ""
    combination: str = ""
    first_step: str = ""
    risks: str = ""
    concept_names: list[str] = Field(default_factory=list)
    confidence: float = Field(default=0.6, ge=0.0, le=1.0)


class ProposalDraft(BaseModel):
    ideas: list[ProposedIdea] = Field(default_factory=list)


class ProposalDeepDive(BaseModel):
    """Structured deepen output — rendered to markdown deterministically."""

    goal: str = ""
    approach: str = ""
    data_needed: str = ""
    first_experiment: str = ""
    metrics: str = ""


DiscoveryJudge = Callable[[str], Awaitable[JudgeReport]]
DiscoveryTitler = Callable[[str], Awaitable[str]]
DiscoveryProposer = Callable[[str], Awaitable[ProposalDraft]]
DiscoveryDeepener = Callable[[str], Awaitable[ProposalDeepDive]]
_AUTO_JUDGE = object()
_AUTO_TITLER = object()
_AUTO_PROPOSER = object()

# How many proposals one run aims for — enough to react to, not a wall of text.
_PROPOSAL_TARGET = 4


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
    proposer: DiscoveryProposer | None | object = _AUTO_PROPOSER,
) -> DiscoveryReport:
    """Create a persisted-ready discovery report from selected or random sessions.

    The first stage intentionally uses broad deterministic recall (similarity,
    lexical, structural and graph-importance signals). If an LLM judge is
    available, it decides which broad candidates are real knowledge crossings;
    otherwise deterministic findings are still returned so the feature remains
    useful without credentials. On top of the findings, a proposer synthesizes
    boss-facing innovation proposals (steered by ``request.intent``, avoiding
    titles already kept/discarded in earlier runs over the same sets), with a
    deterministic template fallback. An LLM titler names the report.
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
            intent=request.intent,
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
    if proposer is _AUTO_PROPOSER:
        proposer = make_proposer_or_none()
    proposals = await _synthesize_proposals(capped, contexts, request.intent, proposer)
    title = await _title_for(capped, contexts, titler)
    return DiscoveryReport(
        title=title,
        mode=request.mode,
        intent=request.intent,
        session_ids=[ctx.session.session_id for ctx in contexts],
        findings=capped,
        proposals=proposals,
        bridge_graph=_bridge_graph(capped, proposals),
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
    if len(contexts) > 1:
        signatures = {context.graph.provenance.embedding_signature for context in contexts}
        if "" in signatures or len(signatures) != 1:
            raise DiscoveryInputError(
                "所选资料集的 embedding 指纹缺失或不一致，请用当前 embedding 配置重新运行各知识图谱流程。"
            )
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


# ── innovation proposals (the "boss over department reports" layer) ─────────

_PROPOSER_SYSTEM = (
    "你是企业创新顾问。各部门各交了一份资料（知识库），下面给出算法找到的跨资料知识桥接点。"
    "你的任务是替老板把桥接点变成可执行的跨部门创新提案：组合两边已有的能力，而不是空想。"
    "每条提案必须点名用到的概念（concept_names 必须逐字取自候选桥接点中的概念名，且至少两个、来自不同资料）。"
    "只输出 JSON。"
)

_DEEPEN_SYSTEM = (
    "你是企业创新顾问。把给定的跨部门创新提案展开成一个最小可执行方案。"
    "只基于提供的证据与提案内容，不要虚构不存在的资源。每个字段一两句话，中文。只输出 JSON。"
)

# relation_type → first-step template for the no-LLM fallback proposals.
_FALLBACK_FIRST_STEP: dict[str, str] = {
    "method_to_application": "挑一个真实业务场景，把一方的方法做成最小迁移试点",
    "complement": "把两边的做法拼成一个组合方案，先在小范围试运行",
    "same_under_different_terms": "统一两边术语并合并文档，消除重复建设",
    "contradiction": "组织两个团队对齐口径，明确各自成立的边界条件",
    "analogy": "按类比把一方的成熟做法映射到另一方的问题上做 PoC",
    "prerequisite": "把前置知识做成对方团队的入门材料，打通协作语言",
    "shared_context": "围绕共同场景立一个跨部门联合调研课题",
    "open_question": "把这个开放问题立项为联合探索任务，先收集双方数据",
}


def make_proposer_or_none() -> DiscoveryProposer | None:
    """Structured proposal drafter — prefers the chat binding (generative quality),
    falls back to critic(→graph). Public so the API layer reuses the same seam."""
    for purpose in (Purpose.chat, Purpose.critic):
        try:
            model = factory.build_chat_model(purpose, temperature=0.7)
            method = factory.structured_output_method(purpose)
        except Exception:
            continue
        caller = make_structured(model, ProposalDraft, system=_PROPOSER_SYSTEM, method=method)

        async def _proposer(prompt: str) -> ProposalDraft:
            return await caller(prompt)

        return _proposer
    return None


def make_deepener_or_none() -> DiscoveryDeepener | None:
    for purpose in (Purpose.chat, Purpose.critic):
        try:
            model = factory.build_chat_model(purpose, temperature=0.4)
            method = factory.structured_output_method(purpose)
        except Exception:
            continue
        caller = make_structured(model, ProposalDeepDive, system=_DEEPEN_SYSTEM, method=method)

        async def _deepener(prompt: str) -> ProposalDeepDive:
            return await caller(prompt)

        return _deepener
    return None


async def _synthesize_proposals(
    findings: list[DiscoveryFinding],
    contexts: list[DiscoveryContext],
    intent: str,
    proposer: DiscoveryProposer | None,
) -> list[InnovationProposal]:
    if not findings:
        return []
    if proposer is not None:
        try:
            draft = await proposer(_proposal_prompt(findings, contexts, intent, _avoid_titles(contexts)))
            proposals = _proposals_from_draft(draft, findings, contexts)
            if proposals:
                return proposals
            logger.warning(
                "proposer returned %d ideas but none survived grounding — using fallback proposals",
                len(draft.ideas),
            )
        except Exception:
            logger.exception("proposer failed — using fallback proposals")
    return _fallback_proposals(findings)


# json_mode relies on the prompt to convey the exact shape (only json_schema mode
# enforces it server-side), so both LLM prompts embed an explicit format example.
_PROPOSAL_FORMAT_HINT = (
    '{"ideas":[{"title":"≤20字","pitch":"一句话价值","combination":"怎么组合两边能力",'
    '"first_step":"最小的第一步行动","risks":"主要风险或未知",'
    '"concept_names":["概念名A","概念名B"],"confidence":0.7}]}'
)

_DEEPEN_FORMAT_HINT = (
    '{"goal":"目标","approach":"做法","data_needed":"所需数据或资源",'
    '"first_experiment":"首个实验","metrics":"衡量指标"}'
)


def _proposal_prompt(
    findings: list[DiscoveryFinding],
    contexts: list[DiscoveryContext],
    intent: str,
    avoid: list[str],
) -> str:
    lines = [
        f"请基于下面的桥接点提出最多 {_PROPOSAL_TARGET} 条跨部门创新提案。",
        f"输出 JSON object，形如：{_PROPOSAL_FORMAT_HINT}",
        "concept_names 必须逐字取自下方桥接点中的概念名，每条提案至少两个、且来自不同资料。",
    ]
    if intent.strip():
        lines.append(f"老板的意图：{intent.strip()}（提案要向这个方向靠拢）")
    if avoid:
        lines.append("以下提案此前已被处理过，不要重复或换皮再提：" + "；".join(avoid))
    lines.append("")
    lines.append("各部门资料：")
    for ctx in contexts:
        lines.append(f"- {ctx.session.course_title} / {ctx.session.lecture_title}")
    lines.append("")
    lines.append("桥接点：")
    for finding in findings:
        parts = "、".join(
            f"{p.concept_name}（{p.lecture_title}）" for p in finding.participants
        )
        lines.append(f"- [{finding.relation_type}] {finding.title}：{finding.summary}｜概念：{parts}")
    return "\n".join(lines)


def _avoid_titles(contexts: list[DiscoveryContext], *, cap: int = 12) -> list[str]:
    """Titles of proposals the boss already kept/discarded over any of these sets —
    fed to the proposer so reruns explore instead of repeating."""
    selected = {ctx.session.session_id for ctx in contexts}
    titles: list[str] = []
    try:
        reports = local.list_discovery_reports()
    except Exception:
        return []
    for report in reports:
        if selected.isdisjoint(set(report.session_ids)):
            continue
        for proposal in report.proposals:
            if proposal.status in ("kept", "discarded") and proposal.title:
                titles.append(proposal.title)
    return list(dict.fromkeys(titles))[:cap]


def _proposals_from_draft(
    draft: ProposalDraft, findings: list[DiscoveryFinding], contexts: list[DiscoveryContext]
) -> list[InnovationProposal]:
    """Ground LLM ideas: every referenced concept must exist in the findings, and a
    proposal must span ≥2 concepts (from ≥2 sets when the run is cross-set)."""
    # Concept lookup is forgiving: raw and parenthetical-stripped forms both key the
    # map (models cite "信号量" while the graph stored "信号量 (Semaphore)", or append
    # the set name shown in the prompt). A key maps to ALL matching participants so
    # the same surface name on two sets resolves to both — not just the first one.
    by_name: dict[str, list[DiscoveryParticipant]] = {}
    registered: set[tuple[str, str, str]] = set()
    evidence_by_key: dict[tuple[str, str], list[DiscoveryEvidence]] = {}
    for finding in findings:
        for participant in finding.participants:
            for key in {participant.concept_name.strip().lower(), _clean_concept_name(participant.concept_name).lower()}:
                marker = (key, str(participant.session_id), participant.concept_id)
                if key and marker not in registered:
                    registered.add(marker)
                    by_name.setdefault(key, []).append(participant)
        for item in finding.evidence:
            evidence_by_key.setdefault((str(item.session_id), item.concept_id), []).append(item)

    cross_set_run = len({str(ctx.session.session_id) for ctx in contexts}) >= 2
    out: list[InnovationProposal] = []
    seen_titles: set[str] = set()
    for idea in draft.ideas[: _PROPOSAL_TARGET * 2]:
        resolved: list[DiscoveryParticipant] = []
        seen_keys: set[tuple[str, str]] = set()
        for name in idea.concept_names:
            matches = by_name.get(name.strip().lower()) or by_name.get(_clean_concept_name(name).lower()) or []
            unused = [p for p in matches if (str(p.session_id), p.concept_id) not in seen_keys]
            if not unused:
                continue
            # Prefer a participant from a set not yet in the proposal, so citing two
            # concepts that both exist in several sets still yields a cross-set idea.
            used_sessions = {str(p.session_id) for p in resolved}
            participant = next((p for p in unused if str(p.session_id) not in used_sessions), unused[0])
            seen_keys.add((str(participant.session_id), participant.concept_id))
            resolved.append(participant)
        if len(resolved) < 2:
            continue
        if cross_set_run and len({str(p.session_id) for p in resolved}) < 2:
            continue
        title = idea.title.strip() or " × ".join(p.concept_name for p in resolved[:2])
        if title.lower() in seen_titles:
            continue
        seen_titles.add(title.lower())
        evidence: list[DiscoveryEvidence] = []
        evidence_seen: set[str] = set()
        for participant in resolved:
            for item in evidence_by_key.get((str(participant.session_id), participant.concept_id), []):
                # Dedup by text, not chunk_id: overlapping chunks (sentence carry-over)
                # produce near-identical quotes that read as duplicates on the card.
                marker = item.snippet[:80]
                if marker in evidence_seen:
                    continue
                evidence_seen.add(marker)
                evidence.append(item)
        out.append(
            InnovationProposal(
                title=title[:60],
                pitch=idea.pitch.strip(),
                combination=idea.combination.strip(),
                first_step=idea.first_step.strip(),
                risks=idea.risks.strip(),
                confidence=round(idea.confidence, 4),
                sources=resolved,
                evidence=evidence[:4],
            )
        )
        if len(out) >= _PROPOSAL_TARGET:
            break
    return out


def _fallback_proposals(findings: list[DiscoveryFinding], *, cap: int = 3) -> list[InnovationProposal]:
    """No-LLM proposals composed from the strongest cross-set findings."""
    ranked = sorted(findings, key=lambda f: f.confidence, reverse=True)
    cross = [f for f in ranked if len({str(p.session_id) for p in f.participants}) >= 2]
    out: list[InnovationProposal] = []
    seen_pairs: set[frozenset[str]] = set()
    for finding in cross or ranked:
        participants = finding.participants[:2]
        if len(participants) < 2:
            continue
        pair = frozenset(f"{p.session_id}:{p.concept_id}" for p in participants)
        if pair in seen_pairs:
            continue
        seen_pairs.add(pair)
        left, right = participants[0], participants[1]
        out.append(
            InnovationProposal(
                title=f"{_clean_concept_name(left.concept_name)} × {_clean_concept_name(right.concept_name)}"[:60],
                pitch=f"把「{left.lecture_title}」与「{right.lecture_title}」的这两块能力组合起来。",
                combination=finding.summary,
                first_step=_FALLBACK_FIRST_STEP.get(finding.relation_type, _FALLBACK_FIRST_STEP["shared_context"]),
                risks="桥接点由算法信号提示，尚未经模型或人工确认，需要先验证关联是否真实成立。",
                confidence=round(min(0.9, finding.confidence), 4),
                sources=list(participants),
                evidence=finding.evidence[:4],
            )
        )
        if len(out) >= cap:
            break
    return out


def _render_deep_dive(dive: ProposalDeepDive) -> str:
    rows = [
        ("目标", dive.goal),
        ("做法", dive.approach),
        ("所需数据 / 资源", dive.data_needed),
        ("首个实验", dive.first_experiment),
        ("衡量指标", dive.metrics),
    ]
    return "\n".join(f"**{label}**：{value.strip()}" for label, value in rows if value.strip())


async def deepen_proposal(
    report: DiscoveryReport, proposal_id: str, deepener: DiscoveryDeepener
) -> DiscoveryReport:
    """Expand one proposal into a minimal executable plan (persisted by the caller)."""
    proposal = next((p for p in report.proposals if p.proposal_id == proposal_id), None)
    if proposal is None:
        raise KeyError(proposal_id)
    lines = [
        f"把下面的提案展开成最小可执行方案，输出 JSON object，形如：{_DEEPEN_FORMAT_HINT}",
        f"提案：{proposal.title}",
        f"价值：{proposal.pitch}",
        f"组合：{proposal.combination}",
        f"第一步：{proposal.first_step}",
        f"风险：{proposal.risks}",
        "涉及：" + "、".join(f"{p.lecture_title}/{p.concept_name}" for p in proposal.sources),
        "证据：",
        *[f"- {e.lecture_title}/{e.concept_name}: {e.snippet}" for e in proposal.evidence[:4]],
    ]
    if report.intent:
        lines.insert(1, f"老板意图：{report.intent}")
    dive = await deepener("\n".join(lines))
    rendered = _render_deep_dive(dive)
    if not rendered:
        raise ValueError("deepen returned an empty plan")
    proposal.deep_dive = rendered
    return report


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


def _bridge_graph(
    findings: list[DiscoveryFinding], proposals: list[InnovationProposal] | None = None
) -> DiscoveryBridgeGraph:
    """Proposal-centric graph (set → concept → proposal) when proposals exist;
    the legacy finding-centric layout otherwise (old persisted reports keep it too)."""
    if proposals:
        return _proposal_graph(proposals)
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


def _proposal_graph(proposals: list[InnovationProposal]) -> DiscoveryBridgeGraph:
    nodes: dict[str, DiscoveryBridgeNode] = {}
    edges: dict[tuple[str, str, str], DiscoveryBridgeEdge] = {}
    for proposal in proposals:
        proposal_node = f"proposal:{proposal.proposal_id}"
        nodes[proposal_node] = DiscoveryBridgeNode(
            id=proposal_node,
            label=proposal.title,
            node_type="proposal",
            metadata={
                "proposal_id": proposal.proposal_id,
                "pitch": proposal.pitch,
                "status": proposal.status,
                "confidence": proposal.confidence,
            },
        )
        for participant in proposal.sources:
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
            edges[(session_node, concept_node, "provides")] = DiscoveryBridgeEdge(
                source=session_node, target=concept_node, edge_type="provides", weight=1.0
            )
            edges[(concept_node, proposal_node, "feeds")] = DiscoveryBridgeEdge(
                source=concept_node,
                target=proposal_node,
                edge_type="feeds",
                weight=proposal.confidence,
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
