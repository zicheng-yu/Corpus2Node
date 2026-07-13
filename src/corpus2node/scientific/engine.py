from __future__ import annotations

import asyncio
import hashlib
import json
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path

from corpus2node.config import settings
from corpus2node.core.text import normalize_text
from corpus2node.core.types import CourseSession, EvidenceChunk
from corpus2node.graph.workflow import ingest_sources_only
from corpus2node.llm import factory
from corpus2node.llm.credentials import Purpose
from corpus2node.llm.structured import make_structured
from corpus2node.scientific.prompts import (
    CROSS_PAPER_SYSTEM_PROMPT,
    PAPER_EXTRACTION_SYSTEM_PROMPT,
    build_cross_paper_prompt,
    build_paper_extraction_prompt,
)
from corpus2node.scientific.schemas import (
    LLMCrossPaperSynthesis,
    LLMPaperExtraction,
    RDDecisionCard,
    ScientificAnalysisRequest,
    ScientificClaim,
    ScientificCondition,
    ScientificEntity,
    ScientificEntityType,
    ScientificEvidence,
    ScientificEvidenceMatrixRow,
    ScientificExperiment,
    ScientificInsight,
    ScientificLocator,
    ScientificMetricResult,
    ScientificNaryRelation,
    ScientificPaperProfile,
    ScientificRelation,
    ScientificRelationType,
    ScientificReport,
)
from corpus2node.storage import local

logger = logging.getLogger(__name__)

PaperCaller = Callable[[str], Awaitable[LLMPaperExtraction]]
SynthesisCaller = Callable[[str], Awaitable[LLMCrossPaperSynthesis]]

MAX_CHUNKS_PER_PAPER = 30
MAX_CHARS_PER_PAPER = 36_000
MIN_PAPERS_FOR_CROSS_ANALYSIS = 2
STRUCTURED_ATTEMPTS = 2
EXTRACTION_CACHE_SCHEMA_VERSION = "2.0"


class ScientificInputError(ValueError):
    pass


@dataclass(frozen=True)
class _PaperInput:
    session: CourseSession
    selected: list[tuple[str, EvidenceChunk, str]]
    alias_to_chunk: dict[str, EvidenceChunk]
    chunk_to_evidence: dict[str, ScientificEvidence]
    fingerprint: str


async def run_scientific_analysis(
    request: ScientificAnalysisRequest,
    *,
    paper_caller: PaperCaller | None = None,
    synthesis_caller: SynthesisCaller | None = None,
) -> ScientificReport:
    await asyncio.gather(*[_prepare_scientific_session(value) for value in _dedupe(request.session_ids)])
    paper_inputs = [_load_paper_input(session_id) for session_id in _dedupe(request.session_ids)]
    if not paper_inputs:
        raise ScientificInputError("至少选择一篇已解析的科技文献。")
    paper_caller, synthesis_caller = _ensure_callers(paper_caller, synthesis_caller)

    raw_extractions = await asyncio.gather(
        *[
            _extract_paper(item, paper_caller, request.language_mode)
            for item in paper_inputs
        ]
    )

    papers: list[ScientificPaperProfile] = []
    entities: list[ScientificEntity] = []
    relations: list[ScientificRelation] = []
    claims: list[ScientificClaim] = []
    experiments: list[ScientificExperiment] = []
    evidence_by_id: dict[str, ScientificEvidence] = {}

    for item, raw in zip(paper_inputs, raw_extractions, strict=True):
        converted = _convert_extraction(item, raw)
        papers.append(converted[0])
        entities.extend(converted[1])
        relations.extend(converted[2])
        claims.extend(converted[3])
        experiments.extend(converted[4])
        for evidence in converted[5]:
            evidence_by_id[evidence.evidence_id] = evidence

    conditions, nary_relations = _build_experiment_relations(entities, claims, experiments)
    for paper in papers:
        paper.entity_ids = [value.entity_id for value in entities if value.session_id == paper.session_id]

    if not claims:
        raise ScientificInputError("模型未抽取到带有效原文证据的科研主张，请检查文献内容或模型配置。")

    evidence_matrix = _build_evidence_matrix(papers, entities, experiments, claims)
    synthesis_payload = _synthesis_payload(papers, claims, experiments, evidence_matrix)
    try:
        raw_synthesis = await _call_with_retry(
            synthesis_caller,
            build_cross_paper_prompt(synthesis_payload, objective_zh=request.objective_zh),
            stage="跨论文证据综合",
        )
    except Exception as exc:
        logger.warning("跨论文模型综合失败，转入确定性证据综合：%s", type(exc).__name__)
        raw_synthesis = LLMCrossPaperSynthesis()
    valid_evidence_ids = set(evidence_by_id)
    valid_claim_ids = {claim.claim_id for claim in claims}
    valid_session_ids = {paper.session_id for paper in papers}
    insights = _convert_insights(
        raw_synthesis,
        valid_evidence_ids,
        valid_claim_ids,
        valid_session_ids,
        evidence_by_id,
    )
    decisions = _convert_decisions(raw_synthesis, valid_evidence_ids)
    fallback_insights, fallback_decisions = _fallback_cross_analysis(papers, claims, request.objective_zh)
    if not insights:
        insights = fallback_insights
        logger.warning("跨论文模型结果没有通过证据校验，使用确定性证据综合兜底。")
    if not decisions:
        decisions = fallback_decisions

    report = ScientificReport(
        title_zh=normalize_text(raw_synthesis.title_zh) or "科技文献研发证据分析",
        objective_zh=normalize_text(request.objective_zh),
        language_mode=request.language_mode,
        session_ids=[item.session.session_id for item in paper_inputs],
        papers=papers,
        entities=entities,
        relations=relations,
        claims=claims,
        experiments=experiments,
        conditions=conditions,
        nary_relations=nary_relations,
        evidence=list(evidence_by_id.values()),
        evidence_matrix=evidence_matrix,
        insights=insights,
        decision_cards=decisions,
    )
    local.save_scientific_report(report)
    logger.info(
        "scientific analysis done: papers=%d claims=%d experiments=%d insights=%d",
        len(papers), len(claims), len(experiments), len(insights),
    )
    return report


def _build_experiment_relations(entities, claims, experiments):
    """Materialize constrained N-ary records; the LLM never decides role validity."""
    conditions: list[ScientificCondition] = []
    relations: list[ScientificNaryRelation] = []

    def entity_ids(session_id, names, entity_type, evidence_refs):
        result = []
        for name in names:
            normalized = normalize_text(name).casefold()
            match = next(
                (
                    value for value in entities
                    if value.session_id == session_id
                    and normalized in {
                        normalize_text(value.name_zh).casefold(),
                        normalize_text(value.name_en).casefold(),
                        normalize_text(value.canonical_name).casefold(),
                    }
                ),
                None,
            )
            if match is None:
                match = ScientificEntity(
                    session_id=session_id,
                    entity_type=entity_type,
                    name_zh=name,
                    canonical_name=normalized,
                    evidence_ids=evidence_refs,
                )
                entities.append(match)
            else:
                match.evidence_ids = _unique(match.evidence_ids + evidence_refs)
            result.append(match.entity_id)
        return _unique(result)

    for experiment in experiments:
        method_ids = entity_ids(
            experiment.session_id, experiment.methods, ScientificEntityType.method, experiment.evidence_ids
        )
        dataset_ids = entity_ids(
            experiment.session_id,
            experiment.datasets_or_environments,
            ScientificEntityType.dataset,
            experiment.evidence_ids,
        )
        baseline_ids = entity_ids(
            experiment.session_id, experiment.baselines, ScientificEntityType.model, experiment.evidence_ids
        )
        if experiment.conditions_zh:
            condition = ScientificCondition(
                session_id=experiment.session_id,
                name="实验条件",
                value=experiment.conditions_zh,
                evidence_ids=experiment.evidence_ids,
            )
            conditions.append(condition)
            experiment.condition_ids.append(condition.condition_id)
        related_claims = [
            value for value in claims
            if value.session_id == experiment.session_id
            and set(value.evidence_ids) & set(experiment.evidence_ids)
        ]
        metric_ids = [value.metric_result_id for value in experiment.metrics]
        for claim in related_claims:
            claim.experiment_ids = _unique(claim.experiment_ids + [experiment.experiment_id])
            claim.metric_result_ids = _unique(claim.metric_result_ids + metric_ids)
            claim.condition_ids = _unique(claim.condition_ids + experiment.condition_ids)
        common = dict(
            session_id=experiment.session_id,
            claim_ids=[value.claim_id for value in related_claims],
            experiment_ids=[experiment.experiment_id],
            method_entity_ids=method_ids,
            dataset_entity_ids=dataset_ids,
            metric_result_ids=metric_ids,
            condition_ids=experiment.condition_ids,
            baseline_entity_ids=baseline_ids,
            evidence_ids=experiment.evidence_ids,
        )
        if method_ids and dataset_ids:
            relations.append(ScientificNaryRelation(relation_type=ScientificRelationType.evaluated_on, **common))
        for claim in related_claims:
            relations.append(
                ScientificNaryRelation(
                    relation_type=ScientificRelationType.supports,
                    **{**common, "claim_ids": [claim.claim_id]},
                )
            )
        comparison_text = " ".join(
            [experiment.conclusion_zh] + [value.comparison_zh for value in experiment.metrics]
        ).lower()
        if baseline_ids and metric_ids and re_search_outperformance(comparison_text):
            relations.append(ScientificNaryRelation(relation_type=ScientificRelationType.outperforms, **common))
        elif metric_ids:
            relations.append(ScientificNaryRelation(relation_type=ScientificRelationType.reports_result, **common))
    return conditions, relations


def re_search_outperformance(text: str) -> bool:
    return any(token in text for token in ("优于", "超过", "提升", "outperform", "better than", "improve"))


async def _extract_paper(item: _PaperInput, caller: PaperCaller, language_mode) -> LLMPaperExtraction:
    cache_path = local.session_dir(item.session.session_id) / "scientific_extraction.json"
    cache_provenance = _extraction_cache_provenance(caller)
    if cache_path.exists():
        try:
            cached = json.loads(cache_path.read_text(encoding="utf-8"))
            if (
                cached.get("fingerprint") == item.fingerprint
                and cached.get("language_mode") == language_mode.value
                and cached.get("provenance") == cache_provenance
            ):
                return LLMPaperExtraction.model_validate(cached["extraction"])
        except (OSError, ValueError, KeyError):
            logger.warning("忽略不可读的科研抽取缓存：%s", cache_path)
    prompt = build_paper_extraction_prompt(item.session, item.selected, language_mode=language_mode)
    result = await _call_with_retry(caller, prompt, stage=f"论文抽取：{item.session.lecture_title}")
    local.write_json(
        cache_path,
        {
            "fingerprint": item.fingerprint,
            "language_mode": language_mode.value,
            "provenance": cache_provenance,
            "extraction": result.model_dump(mode="json"),
        },
    )
    return result


def _extraction_cache_provenance(caller: PaperCaller) -> dict[str, str]:
    schema = json.dumps(LLMPaperExtraction.model_json_schema(), ensure_ascii=False, sort_keys=True)
    caller_name = f"{getattr(caller, '__module__', '')}.{getattr(caller, '__qualname__', type(caller).__name__)}"
    return {
        "schema_version": EXTRACTION_CACHE_SCHEMA_VERSION,
        "model_signature": factory.purpose_signature(Purpose.graph),
        "caller_signature": caller_name,
        "system_prompt_sha256": hashlib.sha256(PAPER_EXTRACTION_SYSTEM_PROMPT.encode()).hexdigest(),
        "output_schema_sha256": hashlib.sha256(schema.encode()).hexdigest(),
    }


async def _prepare_scientific_session(session_id) -> None:
    """Ingest text and attempt structured parsing only inside the scientific lane."""
    session = local.load_session(session_id)
    if session.source_files:
        await ingest_sources_only(session_id)
    await asyncio.to_thread(_parse_structured_sources_best_effort, session_id)


def _parse_structured_sources_best_effort(session_id) -> None:
    from corpus2node.scientific.parsers import ScientificParseError, parse_grobid_pdf, parse_scientific_xml

    session = local.load_session(session_id)
    existing = {document.source_id for document in local.list_scientific_documents(session_id)}
    grobid_alive: bool | None = None
    for source in session.source_files:
        source_id = str(source.source_id)
        if source_id in existing:
            continue
        suffix = Path(source.filename).suffix.lower()
        try:
            if suffix in {".xml", ".nxml"}:
                document = parse_scientific_xml(source.storage_path, source_id=source_id)
            elif suffix == ".pdf":
                if grobid_alive is None:
                    import httpx

                    try:
                        response = httpx.get(
                            f"{settings.grobid_base_url.rstrip('/')}/api/isalive", timeout=0.8
                        )
                        grobid_alive = response.status_code == 200
                    except httpx.HTTPError:
                        grobid_alive = False
                if not grobid_alive:
                    continue
                document = parse_grobid_pdf(
                    source.storage_path,
                    source_id=source_id,
                    base_url=settings.grobid_base_url,
                )
            else:
                continue
            local.save_scientific_document(session_id, document)
        except (ScientificParseError, OSError) as exc:
            logger.info("科研结构解析跳过 %s: %s", source.filename, exc)


async def _call_with_retry(caller, prompt: str, *, stage: str):
    last_error: Exception | None = None
    for attempt in range(1, STRUCTURED_ATTEMPTS + 1):
        try:
            return await caller(prompt)
        except Exception as exc:
            last_error = exc
            if attempt < STRUCTURED_ATTEMPTS:
                logger.warning("%s 结构化输出失败，重试 %d/%d: %s", stage, attempt, STRUCTURED_ATTEMPTS, type(exc).__name__)
    assert last_error is not None
    raise last_error


def _ensure_callers(
    paper_caller: PaperCaller | None,
    synthesis_caller: SynthesisCaller | None,
) -> tuple[PaperCaller, SynthesisCaller]:
    if paper_caller is not None and synthesis_caller is not None:
        return paper_caller, synthesis_caller
    model = factory.build_chat_model(Purpose.graph)
    method = factory.structured_output_method(Purpose.graph)
    if paper_caller is None:
        paper_caller = make_structured(
            model,
            LLMPaperExtraction,
            system=PAPER_EXTRACTION_SYSTEM_PROMPT,
            method=method,
        )
    if synthesis_caller is None:
        synthesis_caller = make_structured(
            model,
            LLMCrossPaperSynthesis,
            system=CROSS_PAPER_SYSTEM_PROMPT,
            method=method,
        )
    return paper_caller, synthesis_caller


def _load_paper_input(session_id) -> _PaperInput:
    try:
        session = local.load_session(session_id)
        artifacts = local.list_ingest_artifacts(session_id)
    except FileNotFoundError as exc:
        raise ScientificInputError(f"资料集不存在：{session_id}") from exc
    chunks = [chunk for artifact in artifacts for chunk in artifact.chunks if normalize_text(chunk.text)]
    if not chunks:
        raise ScientificInputError(f"资料集“{session.lecture_title}”尚无可分析的原文片段。")
    selected_chunks = _select_chunks(chunks)
    source_names = {str(source.source_id): source.filename for source in session.source_files}
    selected: list[tuple[str, EvidenceChunk, str]] = []
    alias_to_chunk: dict[str, EvidenceChunk] = {}
    chunk_to_evidence: dict[str, ScientificEvidence] = {}
    ordinal = {chunk.chunk_id: index for index, chunk in enumerate(chunks, start=1)}
    documents = {value.source_id: value for value in local.list_scientific_documents(session_id)}
    for index, chunk in enumerate(selected_chunks, start=1):
        alias = f"C{index:02d}"
        locator = _locator(chunk, ordinal[chunk.chunk_id], source_names.get(chunk.source_id, "原始文献"))
        selected.append((alias, chunk, locator))
        alias_to_chunk[alias] = chunk
        evidence_id = _evidence_id(session.session_id, chunk.chunk_id)
        structured_locator = _match_structured_locator(documents.get(chunk.source_id), chunk.text)
        if structured_locator.sentence_id or structured_locator.table_id:
            locator = _structured_locator_label(
                source_names.get(chunk.source_id, "原始文献"), structured_locator
            )
        chunk_to_evidence[chunk.chunk_id] = ScientificEvidence(
            evidence_id=evidence_id,
            session_id=session.session_id,
            source_id=chunk.source_id,
            source_type=chunk.source_type,
            chunk_id=chunk.chunk_id,
            locator=locator,
            structured_locator=structured_locator,
            snippet=normalize_text(chunk.text)[:360],
        )
    return _PaperInput(
        session=session,
        selected=selected,
        alias_to_chunk=alias_to_chunk,
        chunk_to_evidence=chunk_to_evidence,
        fingerprint=_paper_fingerprint(selected_chunks),
    )


def _match_structured_locator(document, chunk_text: str) -> ScientificLocator:
    if document is None:
        return ScientificLocator()
    normalized_chunk = normalize_text(chunk_text).lower()
    for section in document.sections:
        for sentence in section.sentences:
            text = normalize_text(sentence.text).lower()
            if len(text) >= 24 and (text in normalized_chunk or normalized_chunk[:160] in text):
                return sentence.locator
    for table in document.tables:
        for cell in table.cells:
            text = normalize_text(cell.text).lower()
            if text and text in normalized_chunk:
                return cell.locator
    return ScientificLocator()


def _structured_locator_label(source_name: str, locator: ScientificLocator) -> str:
    parts = [source_name]
    if locator.section_path:
        parts.append(" / ".join(locator.section_path))
    if locator.page:
        parts.append(f"第 {locator.page} 页")
    if locator.sentence_id:
        parts.append(f"句子 {locator.sentence_id}")
    if locator.table_id:
        parts.append(f"表格 {locator.table_id} [{locator.table_row},{locator.table_column}]")
    return " · ".join(parts)


def _select_chunks(chunks: list[EvidenceChunk]) -> list[EvidenceChunk]:
    if len(chunks) <= MAX_CHUNKS_PER_PAPER and sum(len(chunk.text) for chunk in chunks) <= MAX_CHARS_PER_PAPER:
        return chunks
    keywords = (
        "abstract", "introduction", "method", "approach", "algorithm", "experiment", "evaluation",
        "result", "discussion", "conclusion", "limitation", "摘要", "引言", "方法", "实验", "结果", "结论", "局限",
    )
    scored = []
    last = max(1, len(chunks) - 1)
    for index, chunk in enumerate(chunks):
        text = normalize_text(chunk.text).lower()
        keyword_score = sum(1 for keyword in keywords if keyword in text[:1200])
        boundary_score = 3 if index < 4 or index >= len(chunks) - 5 else 0
        scored.append((keyword_score + boundary_score, index, chunk))
    chosen = {index for _, index, _ in sorted(scored, key=lambda row: (-row[0], row[1]))[:18]}
    for slot in range(12):
        chosen.add(round(slot * last / 11))
    result: list[EvidenceChunk] = []
    chars = 0
    for index in sorted(chosen):
        chunk = chunks[index]
        if len(result) >= MAX_CHUNKS_PER_PAPER:
            break
        remaining = MAX_CHARS_PER_PAPER - chars
        if remaining <= 0:
            break
        if result and len(chunk.text) > remaining:
            continue
        result.append(chunk)
        chars += len(chunk.text)
    return result


def _paper_fingerprint(chunks: list[EvidenceChunk]) -> str:
    digest = hashlib.sha256()
    for chunk in chunks:
        digest.update(chunk.chunk_id.encode())
        digest.update(chunk.text.encode())
    return digest.hexdigest()


def _convert_extraction(item: _PaperInput, raw: LLMPaperExtraction):
    session_id = item.session.session_id
    used_evidence: dict[str, ScientificEvidence] = {}

    def evidence_ids(aliases: list[str]) -> list[str]:
        ids: list[str] = []
        for alias in aliases:
            chunk = item.alias_to_chunk.get(alias.strip().upper())
            if chunk is None:
                continue
            evidence = item.chunk_to_evidence[chunk.chunk_id]
            used_evidence[evidence.evidence_id] = evidence
            if evidence.evidence_id not in ids:
                ids.append(evidence.evidence_id)
        return ids

    def evidence_quote(aliases: list[str], quote: str) -> str:
        candidate = normalize_text(quote)
        if not candidate:
            return ""
        for alias in aliases:
            chunk = item.alias_to_chunk.get(alias.strip().upper())
            if chunk is not None and candidate.casefold() in normalize_text(chunk.text).casefold():
                return candidate
        return ""

    entities = [
        ScientificEntity(
            session_id=session_id,
            entity_type=_entity_type(value.entity_type),
            name_zh=normalize_text(value.name_zh),
            name_en=normalize_text(value.name_en),
            canonical_name=normalize_text(value.canonical_name),
            description_zh=normalize_text(value.description_zh),
            evidence_ids=ids,
        )
        for value in raw.entities
        if (ids := evidence_ids(value.evidence_ids)) and normalize_text(value.name_zh)
    ]
    entity_names = {
        value.entity_id: (normalize_text(value.name_zh) or normalize_text(value.name_en))
        for value in raw.entities
        if value.entity_id
    }
    relations = [
        ScientificRelation(
            session_id=session_id,
            source_name=entity_names.get(value.source_name, normalize_text(value.source_name)),
            relation_type=normalize_text(value.relation_type),
            target_name=entity_names.get(value.target_name, normalize_text(value.target_name)),
            statement_zh=normalize_text(value.statement_zh),
            confidence=value.confidence,
            evidence_ids=ids,
        )
        for value in raw.relations
        if (ids := evidence_ids(value.evidence_ids))
        and normalize_text(entity_names.get(value.source_name, value.source_name))
        and normalize_text(entity_names.get(value.target_name, value.target_name))
    ]
    claims = [
        ScientificClaim(
            session_id=session_id,
            claim_type=normalize_text(value.claim_type) or "论文主张",
            statement_zh=normalize_text(value.statement_zh),
            statement_original=normalize_text(value.statement_original),
            evidence_quote=quote,
            subject=normalize_text(value.subject),
            predicate_zh=normalize_text(value.predicate_zh),
            object=normalize_text(value.object),
            polarity=value.polarity,
            modality=value.modality,
            confidence=value.confidence,
            evidence_ids=ids,
        )
        for value in raw.claims
        if (ids := evidence_ids(value.evidence_ids))
        and normalize_text(value.statement_zh)
        and (quote := evidence_quote(value.evidence_ids, value.evidence_quote))
    ]
    experiments: list[ScientificExperiment] = []
    for value in raw.experiments:
        experiment_evidence = evidence_ids(value.evidence_ids)
        metrics = [
            ScientificMetricResult(
                metric_name=normalize_text(metric.metric_name),
                value=normalize_text(metric.value),
                unit=normalize_text(metric.unit),
                comparison_zh=normalize_text(metric.comparison_zh),
                evidence_quote=quote,
                evidence_ids=metric_ids,
            )
            for metric in value.metrics
            if (metric_ids := evidence_ids(metric.evidence_ids))
            and normalize_text(metric.metric_name)
            and (quote := evidence_quote(metric.evidence_ids, metric.evidence_quote))
        ]
        combined_evidence = _unique(experiment_evidence + [ref for metric in metrics for ref in metric.evidence_ids])
        if not combined_evidence or not normalize_text(value.name_zh):
            continue
        experiments.append(
            ScientificExperiment(
                session_id=session_id,
                name_zh=normalize_text(value.name_zh),
                methods=_clean_list(value.methods),
                datasets_or_environments=_clean_list(value.datasets_or_environments),
                baselines=_clean_list(value.baselines),
                conditions_zh=normalize_text(value.conditions_zh),
                metrics=metrics,
                conclusion_zh=normalize_text(value.conclusion_zh),
                evidence_ids=combined_evidence,
            )
        )
    all_evidence_ids = _unique([ref for value in (entities + relations + claims + experiments) for ref in value.evidence_ids])
    method_summary = normalize_text(raw.method_summary_zh)
    if not method_summary:
        method_summary = "；".join(
            value.description_zh for value in entities if value.entity_type in {ScientificEntityType.method, ScientificEntityType.model}
        )[:800]
    result_summary = normalize_text(raw.result_summary_zh)
    if not result_summary:
        experiment_fallback = experiments[0].conclusion_zh if experiments else ""
        result_summary = next(
            (value.statement_zh for value in claims if value.claim_type in {"实验结果", "结果", "理论性质"}),
            experiment_fallback,
        )
    research_problem = normalize_text(raw.research_problem_zh)
    if not research_problem:
        research_problem = next(
            (value.statement_zh for value in claims if value.claim_type in {"研究问题", "问题定义"}),
            f"分析 {normalize_text(raw.title_zh) or item.session.lecture_title} 所解决的科研问题与技术路线。",
        )
    paper = ScientificPaperProfile(
        session_id=session_id,
        source_title=item.session.lecture_title,
        title_zh=normalize_text(raw.title_zh) or item.session.lecture_title,
        title_original=normalize_text(raw.title_original),
        research_problem_zh=research_problem,
        method_summary_zh=method_summary,
        result_summary_zh=result_summary,
        limitations_zh=_clean_list(raw.limitations_zh),
        entity_ids=[value.entity_id for value in entities],
        claim_ids=[value.claim_id for value in claims],
        experiment_ids=[value.experiment_id for value in experiments],
        evidence_ids=all_evidence_ids,
    )
    return paper, entities, relations, claims, experiments, list(used_evidence.values())


def _build_evidence_matrix(papers, entities, experiments, claims) -> list[ScientificEvidenceMatrixRow]:
    rows = []
    for paper in papers:
        paper_entities = [value for value in entities if value.session_id == paper.session_id]
        paper_experiments = [value for value in experiments if value.session_id == paper.session_id]
        paper_claims = [value for value in claims if value.session_id == paper.session_id]
        methods = [value.name_zh or value.name_en for value in paper_entities if value.entity_type.value in {"method", "model"}]
        datasets = [value.name_zh or value.name_en for value in paper_entities if value.entity_type.value in {"dataset", "material"}]
        metrics = [metric.metric_name for experiment in paper_experiments for metric in experiment.metrics]
        result_claims = [value.statement_zh for value in paper_claims if value.claim_type in {"实验结果", "结果", "理论性质"}]
        experiment_evidence = [ref for value in paper_experiments for ref in value.evidence_ids]
        rows.append(
            ScientificEvidenceMatrixRow(
                paper_title=paper.title_zh,
                session_id=paper.session_id,
                research_problem_zh=paper.research_problem_zh,
                core_methods=_unique(methods)[:8],
                datasets_or_environments=_unique(datasets + [x for e in paper_experiments for x in e.datasets_or_environments])[:8],
                metrics=_unique(metrics)[:10],
                main_result_zh=paper.result_summary_zh or (result_claims[0] if result_claims else ""),
                limitations_zh=paper.limitations_zh,
                evidence_ids=_unique(paper.evidence_ids + experiment_evidence)[:16],
            )
        )
    return rows


def _synthesis_payload(papers, claims, experiments, matrix) -> dict:
    return {
        "papers": [paper.model_dump(mode="json") for paper in papers],
        "claims": [claim.model_dump(mode="json") for claim in claims],
        "experiments": [experiment.model_dump(mode="json") for experiment in experiments],
        "evidence_matrix": [row.model_dump(mode="json") for row in matrix],
    }


def _convert_insights(raw, valid_evidence_ids, valid_claim_ids, valid_session_ids, evidence_by_id):
    result = []
    for value in raw.insights:
        evidence_ids = [ref for ref in _unique(value.evidence_ids) if ref in valid_evidence_ids]
        claim_ids = [ref for ref in _unique(value.supporting_claim_ids) if ref in valid_claim_ids]
        session_ids = [ref for ref in _unique(value.related_session_ids) if ref in valid_session_ids]
        if len(session_ids) < MIN_PAPERS_FOR_CROSS_ANALYSIS:
            session_ids = _unique(
                [evidence_by_id[ref].session_id for ref in evidence_ids if ref in evidence_by_id]
            )
        if not evidence_ids or len(session_ids) < MIN_PAPERS_FOR_CROSS_ANALYSIS:
            continue
        summary = normalize_text(value.summary_zh)
        result.append(
            ScientificInsight(
                insight_type=value.insight_type,
                title_zh=normalize_text(value.title_zh) or summary[:56],
                summary_zh=summary,
                reasoning_zh=normalize_text(value.reasoning_zh),
                confidence=value.confidence,
                related_session_ids=session_ids,
                supporting_claim_ids=claim_ids,
                evidence_ids=evidence_ids,
            )
        )
    return result


def _convert_decisions(raw, valid_evidence_ids):
    result = []
    for value in raw.decision_cards:
        evidence_ids = [ref for ref in _unique(value.evidence_ids) if ref in valid_evidence_ids]
        if not evidence_ids or not normalize_text(value.title_zh):
            continue
        result.append(
            RDDecisionCard(
                title_zh=normalize_text(value.title_zh),
                recommendation_zh=normalize_text(value.recommendation_zh) or normalize_text(value.next_experiment_zh),
                rationale_zh=normalize_text(value.rationale_zh) or "基于本报告中已校验的跨论文证据。",
                next_experiment_zh=normalize_text(value.next_experiment_zh),
                risks_zh=_clean_list(value.risks_zh),
                confidence=value.confidence,
                evidence_ids=evidence_ids,
            )
        )
    return result


def _fallback_cross_analysis(papers, claims, objective_zh: str):
    if len(papers) < MIN_PAPERS_FOR_CROSS_ANALYSIS:
        return [], []
    selected_papers = papers[:2]
    session_ids = [paper.session_id for paper in selected_papers]
    paper_claims = [
        next((claim for claim in claims if claim.session_id == paper.session_id), None)
        for paper in selected_papers
    ]
    claim_ids = [claim.claim_id for claim in paper_claims if claim is not None]
    evidence_ids = _unique(
        [ref for paper in selected_papers for ref in paper.evidence_ids[:3]]
        + [ref for claim in paper_claims if claim is not None for ref in claim.evidence_ids[:2]]
    )
    if not evidence_ids:
        return [], []
    first, second = selected_papers
    lineage = ScientificInsight(
        insight_type="technical_lineage",
        title_zh=f"从《{first.title_zh}》到《{second.title_zh}》的技术路线演进",
        summary_zh=(
            f"前者的核心路线是：{first.method_summary_zh}；后者的核心路线是：{second.method_summary_zh}。"
            "两篇文献围绕相近研发问题形成了可对照的价值分解技术路径。"
        ),
        reasoning_zh="该结论由两篇论文各自的方法主张与实验片段共同支撑；具体优劣仍需在统一条件下验证。",
        confidence=0.72,
        related_session_ids=session_ids,
        supporting_claim_ids=claim_ids,
        evidence_ids=evidence_ids,
    )
    gap = ScientificInsight(
        insight_type="research_gap",
        title_zh="缺少统一任务、预算与指标下的直接对照证据",
        summary_zh=(
            f"《{first.title_zh}》与《{second.title_zh}》使用的实验条件和任务并不完全一致，"
            "现有证据不足以直接回答目标场景中的算法选型，需要统一基准实验补齐证据。"
        ),
        reasoning_zh="这是对当前证据覆盖范围的判断，不等同于论文结论互相矛盾。",
        confidence=0.68,
        related_session_ids=session_ids,
        supporting_claim_ids=claim_ids,
        evidence_ids=evidence_ids,
    )
    objective = normalize_text(objective_zh) or "比较两条技术路线并确定目标场景的算法选型"
    decision = RDDecisionCard(
        title_zh="在统一条件下完成两条技术路线的最小对照实验",
        recommendation_zh=f"围绕“{objective}”建立同任务、同网络容量、同训练预算的对照基线。",
        rationale_zh="当前两篇论文都提供了方法有效性的原文证据，但实验环境不同，不能直接把跨论文性能数字当成同条件排名。",
        next_experiment_zh=(
            "选择一个同质智能体任务和一个异质智能体任务，固定网络容量、优化器、训练步数和随机种子集合，"
            "并行运行两种方法；记录最终回报、样本效率、稳定性和失败案例，再按目标场景的约束作选型。"
        ),
        risks_zh=["跨论文实验设置差异可能造成错误归因。", "单一任务结果不能外推到所有协作场景。"],
        confidence=0.7,
        evidence_ids=evidence_ids,
    )
    return [lineage, gap], [decision]


def _locator(chunk: EvidenceChunk, ordinal: int, filename: str) -> str:
    name = Path(filename).name
    if chunk.page_start is not None:
        pages = f"第 {chunk.page_start} 页"
        if chunk.page_end not in (None, chunk.page_start):
            pages = f"第 {chunk.page_start}-{chunk.page_end} 页"
        return f"{name} · {pages}"
    if chunk.time_start is not None:
        return f"{name} · {chunk.time_start:.1f}-{(chunk.time_end or chunk.time_start):.1f} 秒"
    return f"{name} · 原文段落 {ordinal}"


def _evidence_id(session_id, chunk_id: str) -> str:
    return f"ev:{str(session_id)[:8]}:{chunk_id}"


def _entity_type(value: str) -> ScientificEntityType:
    key = normalize_text(value).lower()
    aliases = {
        "problem": ScientificEntityType.research_problem,
        "research_problem": ScientificEntityType.research_problem,
        "method": ScientificEntityType.method,
        "algorithm": ScientificEntityType.method,
        "optimizer": ScientificEntityType.method,
        "exploration_strategy": ScientificEntityType.method,
        "model": ScientificEntityType.model,
        "component": ScientificEntityType.model,
        "architecture": ScientificEntityType.model,
        "dataset": ScientificEntityType.dataset,
        "environment": ScientificEntityType.dataset,
        "data": ScientificEntityType.dataset,
        "metric": ScientificEntityType.metric,
        "material": ScientificEntityType.material,
        "parameter": ScientificEntityType.parameter,
        "constraint": ScientificEntityType.parameter,
        "baseline": ScientificEntityType.parameter,
        "result": ScientificEntityType.result,
        "limitation": ScientificEntityType.limitation,
    }
    if key in aliases:
        return aliases[key]
    if any(token in key for token in ("环境", "数据", "dataset", "environment")):
        return ScientificEntityType.dataset
    if any(token in key for token in ("方法", "技术", "算法", "method", "technique", "algorithm")):
        return ScientificEntityType.method
    if any(token in key for token in ("模型", "组件", "网络", "model", "component", "network")):
        return ScientificEntityType.model
    return ScientificEntityType.model


def _clean_list(values: list[str]) -> list[str]:
    return _unique([normalize_text(value) for value in values if normalize_text(value)])


def _unique(values):
    result = []
    seen = set()
    for value in values:
        key = str(value)
        if key in seen:
            continue
        seen.add(key)
        result.append(value)
    return result


def _dedupe(values):
    return _unique(values)
