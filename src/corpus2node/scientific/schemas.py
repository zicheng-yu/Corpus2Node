from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Literal
from uuid import UUID, uuid4

from pydantic import AliasChoices, BaseModel, Field, field_validator, model_validator

from corpus2node.core.clock import utcnow
from corpus2node.core.types import SourceKind


class ScientificLanguageMode(str, Enum):
    zh = "zh"
    zh_bilingual = "zh_bilingual"


class ScientificEntityType(str, Enum):
    research_problem = "research_problem"
    method = "method"
    model = "model"
    dataset = "dataset"
    metric = "metric"
    material = "material"
    parameter = "parameter"
    result = "result"
    limitation = "limitation"


class ScientificRelationType(str, Enum):
    proposes = "PROPOSES"
    extends = "EXTENDS"
    uses = "USES"
    evaluated_on = "EVALUATED_ON"
    measured_by = "MEASURED_BY"
    reports_result = "REPORTS_RESULT"
    outperforms = "OUTPERFORMS"
    supports = "SUPPORTS"
    contradicts = "CONTRADICTS"
    replicates = "REPLICATES"
    limited_by = "LIMITED_BY"
    requires = "REQUIRES"
    derived_from = "DERIVED_FROM"
    related_to = "RELATED_TO"


class ScientificBBox(BaseModel):
    page: int = Field(ge=1)
    x: float
    y: float
    width: float = Field(ge=0)
    height: float = Field(ge=0)


class ScientificLocator(BaseModel):
    section_path: list[str] = Field(default_factory=list)
    sentence_id: str = ""
    page: int | None = Field(default=None, ge=1)
    bboxes: list[ScientificBBox] = Field(default_factory=list)
    table_id: str = ""
    table_row: int | None = Field(default=None, ge=0)
    table_column: int | None = Field(default=None, ge=0)
    formula_id: str = ""
    citation_ids: list[str] = Field(default_factory=list)


class ScientificSentence(BaseModel):
    sentence_id: str
    text: str
    locator: ScientificLocator


class ScientificTableCell(BaseModel):
    cell_id: str
    text: str
    row: int = Field(ge=0)
    column: int = Field(ge=0)
    row_span: int = Field(default=1, ge=1)
    column_span: int = Field(default=1, ge=1)
    locator: ScientificLocator


class ScientificTable(BaseModel):
    table_id: str
    label: str = ""
    caption: str = ""
    cells: list[ScientificTableCell] = Field(default_factory=list)
    locator: ScientificLocator = Field(default_factory=ScientificLocator)


class ScientificFormula(BaseModel):
    formula_id: str
    text: str
    locator: ScientificLocator


class ScientificSection(BaseModel):
    section_id: str
    title: str = ""
    path: list[str] = Field(default_factory=list)
    sentences: list[ScientificSentence] = Field(default_factory=list)
    child_section_ids: list[str] = Field(default_factory=list)


class ScientificDocument(BaseModel):
    document_id: str = Field(default_factory=lambda: str(uuid4()))
    source_id: str
    source_format: Literal["jats", "tei", "grobid_tei"]
    title: str = ""
    sections: list[ScientificSection] = Field(default_factory=list)
    tables: list[ScientificTable] = Field(default_factory=list)
    formulas: list[ScientificFormula] = Field(default_factory=list)
    reference_ids: list[str] = Field(default_factory=list)
    page_dimensions: dict[int, tuple[float, float]] = Field(default_factory=dict)


class ScientificInsightType(str, Enum):
    agreement = "agreement"
    contradiction = "contradiction"
    research_gap = "research_gap"
    transfer_opportunity = "transfer_opportunity"
    technical_lineage = "technical_lineage"


class ScientificAnalysisRequest(BaseModel):
    session_ids: list[UUID] = Field(min_length=1, max_length=12)
    objective_zh: str = Field(default="", max_length=800)
    language_mode: ScientificLanguageMode = ScientificLanguageMode.zh_bilingual


class ScientificParseRequest(BaseModel):
    session_id: UUID
    source_ids: list[UUID] = Field(default_factory=list)


class ScientificEvidence(BaseModel):
    evidence_id: str
    session_id: UUID
    source_id: str
    source_type: SourceKind
    chunk_id: str
    locator: str
    structured_locator: ScientificLocator = Field(default_factory=ScientificLocator)
    snippet: str


class ScientificEntity(BaseModel):
    entity_id: str = Field(default_factory=lambda: str(uuid4()))
    session_id: UUID
    entity_type: ScientificEntityType
    name_zh: str
    name_en: str = ""
    canonical_name: str = ""
    description_zh: str = ""
    evidence_ids: list[str] = Field(default_factory=list)


class ScientificRelation(BaseModel):
    relation_id: str = Field(default_factory=lambda: str(uuid4()))
    session_id: UUID
    source_name: str
    relation_type: ScientificRelationType
    target_name: str
    statement_zh: str = ""
    confidence: float = Field(default=0.7, ge=0.0, le=1.0)
    evidence_ids: list[str] = Field(default_factory=list)

    @field_validator("relation_type", mode="before")
    @classmethod
    def normalize_relation_type(cls, value):
        key = str(value or "").strip()
        return {
            "提出": "PROPOSES", "扩展": "EXTENDS", "改进": "EXTENDS", "使用": "USES", "采用": "USES",
            "评估于": "EVALUATED_ON", "在…上评估": "EVALUATED_ON", "度量": "MEASURED_BY",
            "报告结果": "REPORTS_RESULT", "优于": "OUTPERFORMS", "支持": "SUPPORTS",
            "矛盾": "CONTRADICTS", "复现": "REPLICATES", "受限于": "LIMITED_BY", "限制于": "LIMITED_BY",
            "需要": "REQUIRES", "依赖": "REQUIRES", "源自": "DERIVED_FROM", "相关": "RELATED_TO",
            "比较于": "RELATED_TO", "包含": "RELATED_TO", "导致": "RELATED_TO",
        }.get(key, key.upper() if key.upper() in {item.value for item in ScientificRelationType} else "RELATED_TO")


class ScientificClaim(BaseModel):
    claim_id: str = Field(default_factory=lambda: str(uuid4()))
    session_id: UUID
    claim_type: str
    statement_zh: str
    statement_original: str = ""
    evidence_quote: str = ""
    subject: str = ""
    predicate_zh: str = ""
    object: str = ""
    polarity: Literal["positive", "negative", "neutral", "mixed"] = "neutral"
    modality: Literal["observed", "claimed", "hypothesized", "limited"] = "claimed"
    confidence: float = Field(default=0.7, ge=0.0, le=1.0)
    evidence_ids: list[str] = Field(default_factory=list)
    experiment_ids: list[str] = Field(default_factory=list)
    metric_result_ids: list[str] = Field(default_factory=list)
    condition_ids: list[str] = Field(default_factory=list)


class ScientificMetricResult(BaseModel):
    metric_result_id: str = Field(default_factory=lambda: str(uuid4()))
    metric_name: str
    value: str = ""
    unit: str = ""
    comparison_zh: str = ""
    evidence_quote: str = ""
    evidence_ids: list[str] = Field(default_factory=list)


class ScientificCondition(BaseModel):
    condition_id: str = Field(default_factory=lambda: str(uuid4()))
    session_id: UUID
    name: str
    value: str = ""
    unit: str = ""
    evidence_ids: list[str] = Field(default_factory=list)


class ScientificExperiment(BaseModel):
    experiment_id: str = Field(default_factory=lambda: str(uuid4()))
    session_id: UUID
    name_zh: str
    methods: list[str] = Field(default_factory=list)
    datasets_or_environments: list[str] = Field(default_factory=list)
    baselines: list[str] = Field(default_factory=list)
    conditions_zh: str = ""
    metrics: list[ScientificMetricResult] = Field(default_factory=list)
    conclusion_zh: str = ""
    evidence_ids: list[str] = Field(default_factory=list)
    condition_ids: list[str] = Field(default_factory=list)


class ScientificNaryRelation(BaseModel):
    nary_relation_id: str = Field(default_factory=lambda: str(uuid4()))
    session_id: UUID
    relation_type: ScientificRelationType
    claim_ids: list[str] = Field(default_factory=list)
    experiment_ids: list[str] = Field(default_factory=list)
    method_entity_ids: list[str] = Field(default_factory=list)
    dataset_entity_ids: list[str] = Field(default_factory=list)
    metric_result_ids: list[str] = Field(default_factory=list)
    condition_ids: list[str] = Field(default_factory=list)
    result_entity_ids: list[str] = Field(default_factory=list)
    baseline_entity_ids: list[str] = Field(default_factory=list)
    evidence_ids: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_role_constraints(self):
        required = {
            ScientificRelationType.outperforms: (
                self.experiment_ids and self.baseline_entity_ids and self.metric_result_ids and self.evidence_ids
            ),
            ScientificRelationType.evaluated_on: (
                self.experiment_ids and self.method_entity_ids and self.dataset_entity_ids and self.evidence_ids
            ),
            ScientificRelationType.supports: self.claim_ids and self.evidence_ids,
        }
        if self.relation_type in required and not required[self.relation_type]:
            raise ValueError(f"{self.relation_type.value} 缺少必需角色")
        return self


class ScientificPaperProfile(BaseModel):
    session_id: UUID
    source_title: str
    title_zh: str
    title_original: str = ""
    research_problem_zh: str
    method_summary_zh: str
    result_summary_zh: str
    limitations_zh: list[str] = Field(default_factory=list)
    entity_ids: list[str] = Field(default_factory=list)
    claim_ids: list[str] = Field(default_factory=list)
    experiment_ids: list[str] = Field(default_factory=list)
    evidence_ids: list[str] = Field(default_factory=list)


class ScientificEvidenceMatrixRow(BaseModel):
    paper_title: str
    session_id: UUID
    research_problem_zh: str
    core_methods: list[str] = Field(default_factory=list)
    datasets_or_environments: list[str] = Field(default_factory=list)
    metrics: list[str] = Field(default_factory=list)
    main_result_zh: str = ""
    limitations_zh: list[str] = Field(default_factory=list)
    evidence_ids: list[str] = Field(default_factory=list)


class ScientificInsight(BaseModel):
    insight_id: str = Field(default_factory=lambda: str(uuid4()))
    insight_type: ScientificInsightType
    title_zh: str
    summary_zh: str
    reasoning_zh: str = ""
    confidence: float = Field(default=0.6, ge=0.0, le=1.0)
    related_session_ids: list[UUID] = Field(default_factory=list)
    supporting_claim_ids: list[str] = Field(default_factory=list)
    evidence_ids: list[str] = Field(default_factory=list)


class RDDecisionCard(BaseModel):
    decision_id: str = Field(default_factory=lambda: str(uuid4()))
    title_zh: str
    recommendation_zh: str
    rationale_zh: str
    next_experiment_zh: str
    risks_zh: list[str] = Field(default_factory=list)
    confidence: float = Field(default=0.6, ge=0.0, le=1.0)
    evidence_ids: list[str] = Field(default_factory=list)


class ScientificReport(BaseModel):
    report_id: str = Field(default_factory=lambda: str(uuid4()))
    title_zh: str
    objective_zh: str = ""
    language_mode: ScientificLanguageMode = ScientificLanguageMode.zh_bilingual
    session_ids: list[UUID]
    papers: list[ScientificPaperProfile] = Field(default_factory=list)
    entities: list[ScientificEntity] = Field(default_factory=list)
    relations: list[ScientificRelation] = Field(default_factory=list)
    claims: list[ScientificClaim] = Field(default_factory=list)
    experiments: list[ScientificExperiment] = Field(default_factory=list)
    conditions: list[ScientificCondition] = Field(default_factory=list)
    nary_relations: list[ScientificNaryRelation] = Field(default_factory=list)
    evidence: list[ScientificEvidence] = Field(default_factory=list)
    evidence_matrix: list[ScientificEvidenceMatrixRow] = Field(default_factory=list)
    insights: list[ScientificInsight] = Field(default_factory=list)
    decision_cards: list[RDDecisionCard] = Field(default_factory=list)
    generated_at: datetime = Field(default_factory=utcnow)


# Structured LLM output. Evidence ids are prompt-local aliases (for example C01)
# and are mapped to real chunk ids by the engine before anything is persisted.
class LLMVendorModel(BaseModel):
    """Normalize harmless JSON-mode variants before validating the stable schema."""

    @model_validator(mode="before")
    @classmethod
    def normalize_null_text(cls, value):
        if not isinstance(value, dict):
            return value
        data = dict(value)
        for name, field in cls.model_fields.items():
            if name in data and data[name] is None and field.default == "":
                data[name] = ""
        return data


class LLMPaperEntity(LLMVendorModel):
    entity_id: str = Field(default="", validation_alias=AliasChoices("entity_id", "id"))
    entity_type: str = Field(default="method", validation_alias=AliasChoices("entity_type", "type"))
    name_zh: str = ""
    name_en: str = ""
    canonical_name: str = ""
    description_zh: str = Field(default="", validation_alias=AliasChoices("description_zh", "description"))
    evidence_ids: list[str] = Field(default_factory=list)


class LLMPaperRelation(LLMVendorModel):
    source_name: str = Field(default="", validation_alias=AliasChoices("source_name", "source_id"))
    relation_type: str
    target_name: str = Field(default="", validation_alias=AliasChoices("target_name", "target_id"))
    statement_zh: str = ""
    confidence: float = Field(default=0.7, ge=0.0, le=1.0)
    evidence_ids: list[str] = Field(default_factory=list)

    @field_validator("confidence", mode="before")
    @classmethod
    def normalize_confidence(cls, value):
        return _confidence(value)


class LLMPaperClaim(LLMVendorModel):
    claim_type: str
    statement_zh: str = Field(validation_alias=AliasChoices("statement_zh", "statement"))
    statement_original: str = ""
    evidence_quote: str = ""
    subject: str = ""
    predicate_zh: str = ""
    object: str = ""
    polarity: Literal["positive", "negative", "neutral", "mixed"] = "neutral"
    modality: Literal["observed", "claimed", "hypothesized", "limited"] = "claimed"
    confidence: float = Field(default=0.7, ge=0.0, le=1.0)
    evidence_ids: list[str] = Field(default_factory=list)

    @field_validator("confidence", mode="before")
    @classmethod
    def normalize_confidence(cls, value):
        return _confidence(value)

    @field_validator("polarity", mode="before")
    @classmethod
    def normalize_polarity(cls, value):
        return {
            "正面": "positive", "积极": "positive", "positive": "positive",
            "负面": "negative", "消极": "negative", "negative": "negative",
            "混合": "mixed", "mixed": "mixed", "中性": "neutral", "neutral": "neutral",
        }.get(str(value).strip().lower(), "neutral")

    @field_validator("modality", mode="before")
    @classmethod
    def normalize_modality(cls, value):
        return {
            "观测": "observed", "观察到": "observed", "已证实": "observed", "observed": "observed",
            "断言": "claimed", "声称": "claimed", "claimed": "claimed",
            "假设": "hypothesized", "可能性": "hypothesized", "hypothesized": "hypothesized",
            "受限": "limited", "限制": "limited", "limited": "limited",
        }.get(str(value).strip().lower(), "claimed")


class LLMPaperMetricResult(LLMVendorModel):
    metric_name: str
    value: str = ""
    unit: str = ""
    comparison_zh: str = ""
    evidence_quote: str = ""
    evidence_ids: list[str] = Field(default_factory=list)

    @field_validator("value", "unit", "comparison_zh", "evidence_quote", mode="before")
    @classmethod
    def normalize_scalar_text(cls, value):
        return "" if value is None else str(value)


class LLMPaperExperiment(LLMVendorModel):
    name_zh: str = ""
    methods: list[str] = Field(default_factory=list)
    datasets_or_environments: list[str] = Field(default_factory=list)
    baselines: list[str] = Field(default_factory=list)
    conditions_zh: str = ""
    metrics: list[LLMPaperMetricResult] = Field(default_factory=list)
    conclusion_zh: str = ""
    evidence_ids: list[str] = Field(default_factory=list)

    @model_validator(mode="before")
    @classmethod
    def normalize_vendor_shape(cls, value):
        if not isinstance(value, dict):
            return value
        data = dict(value)
        description = str(data.get("description", "")).strip()
        data.setdefault("name_zh", description[:48] or "论文实验")
        data.setdefault("conditions_zh", description)
        dataset = data.pop("dataset", None)
        if dataset and not data.get("datasets_or_environments"):
            data["datasets_or_environments"] = dataset if isinstance(dataset, list) else [str(dataset)]
        for key in ("methods", "datasets_or_environments", "baselines", "evidence_ids"):
            current = data.get(key)
            if current is None:
                data[key] = []
            elif not isinstance(current, list):
                data[key] = [str(current)]
        data.setdefault("conclusion_zh", data.pop("results", ""))
        evidence_ids = data.get("evidence_ids", [])
        metrics = []
        for metric in data.get("metrics", []):
            if isinstance(metric, str):
                metrics.append({"metric_name": metric, "evidence_ids": evidence_ids})
            elif isinstance(metric, dict) or hasattr(metric, "model_dump"):
                item = dict(metric) if isinstance(metric, dict) else metric.model_dump()
                item.setdefault("evidence_ids", evidence_ids)
                for key in ("value", "unit", "comparison_zh"):
                    if item.get(key) is None:
                        item[key] = ""
                metrics.append(item)
        data["metrics"] = metrics
        return data


class LLMPaperExtraction(LLMVendorModel):
    title_zh: str = Field(default="", validation_alias=AliasChoices("title_zh", "paper_title"))
    title_original: str = Field(default="", validation_alias=AliasChoices("title_original", "paper_title"))
    research_problem_zh: str = ""
    method_summary_zh: str = ""
    result_summary_zh: str = ""
    limitations_zh: list[str] = Field(default_factory=list)
    entities: list[LLMPaperEntity] = Field(default_factory=list)
    relations: list[LLMPaperRelation] = Field(default_factory=list)
    claims: list[LLMPaperClaim] = Field(default_factory=list)
    experiments: list[LLMPaperExperiment] = Field(default_factory=list)

    @field_validator("limitations_zh", mode="before")
    @classmethod
    def normalize_limitations(cls, value):
        if value is None or value == "":
            return []
        return value if isinstance(value, list) else [str(value)]


class LLMCrossPaperInsight(LLMVendorModel):
    insight_type: ScientificInsightType = Field(validation_alias=AliasChoices("insight_type", "type"))
    title_zh: str = Field(default="", validation_alias=AliasChoices("title_zh", "title"))
    summary_zh: str = Field(validation_alias=AliasChoices("summary_zh", "summary", "description_zh"))
    reasoning_zh: str = Field(
        default="",
        validation_alias=AliasChoices("reasoning_zh", "reasoning", "explanation_zh"),
    )
    confidence: float = Field(default=0.6, ge=0.0, le=1.0)
    related_session_ids: list[UUID] = Field(
        default_factory=list,
        validation_alias=AliasChoices(
            "related_session_ids", "related_paper_session_ids", "papers_involved", "related_papers"
        ),
    )
    supporting_claim_ids: list[str] = Field(default_factory=list)
    evidence_ids: list[str] = Field(default_factory=list)

    @field_validator("confidence", mode="before")
    @classmethod
    def normalize_confidence(cls, value):
        return _confidence(value)

    @field_validator("insight_type", mode="before")
    @classmethod
    def normalize_insight_type(cls, value):
        return _insight_type(value)


class LLMDecisionCard(LLMVendorModel):
    title_zh: str = Field(validation_alias=AliasChoices("title_zh", "title"))
    recommendation_zh: str = Field(
        default="",
        validation_alias=AliasChoices(
            "recommendation_zh", "recommendation", "priority_action_zh", "action_zh", "decision_zh",
            "experiment_design_zh",
        )
    )
    rationale_zh: str = Field(
        default="",
        validation_alias=AliasChoices(
            "rationale_zh", "rationale", "justification_zh", "expected_outcome_zh", "context_zh", "objective_zh"
        )
    )
    next_experiment_zh: str = Field(validation_alias=AliasChoices("next_experiment_zh", "next_experiment"))
    risks_zh: list[str] = Field(
        default_factory=list,
        validation_alias=AliasChoices("risks_zh", "risk_and_mitigation_zh"),
    )
    confidence: float = Field(default=0.6, ge=0.0, le=1.0)
    evidence_ids: list[str] = Field(
        default_factory=list,
        validation_alias=AliasChoices("evidence_ids", "supporting_evidence_ids", "evidence_refs"),
    )

    @field_validator("confidence", mode="before")
    @classmethod
    def normalize_confidence(cls, value):
        return _confidence(value)

    @field_validator("risks_zh", mode="before")
    @classmethod
    def normalize_risks(cls, value):
        if value is None or value == "":
            return []
        return value if isinstance(value, list) else [str(value)]


class LLMCrossPaperSynthesis(LLMVendorModel):
    title_zh: str = Field(default="科技文献研发证据分析", validation_alias=AliasChoices("title_zh", "title"))
    insights: list[LLMCrossPaperInsight] = Field(
        default_factory=list,
        validation_alias=AliasChoices("insights", "insight_cards", "cross_paper_insights"),
    )
    decision_cards: list[LLMDecisionCard] = Field(default_factory=list)

    @model_validator(mode="before")
    @classmethod
    def normalize_cross_vendor_shape(cls, value):
        if not isinstance(value, dict):
            return value
        data = dict(value)
        raw_insights = _first_list(
            data,
            "insights", "insight_cards", "cross_paper_insights", "cross_paper_findings", "findings",
        )
        insights = []
        for raw in raw_insights:
            if hasattr(raw, "model_dump"):
                raw = raw.model_dump()
            if not isinstance(raw, dict):
                continue
            summary = _first_text(raw, "summary_zh", "description_zh", "summary", "description")
            if not summary:
                continue
            insights.append(
                {
                    "insight_type": _insight_type(_first_text(raw, "insight_type", "type", "relation_type")),
                    "title_zh": _first_text(raw, "title_zh", "title") or summary[:56],
                    "summary_zh": summary,
                    "reasoning_zh": _first_text(raw, "reasoning_zh", "reasoning", "explanation_zh", "explanation"),
                    "confidence": raw.get("confidence", 0.65),
                    "related_session_ids": _first_list(
                        raw, "related_session_ids", "related_paper_session_ids", "papers_involved", "related_papers",
                    ),
                    "supporting_claim_ids": _first_list(raw, "supporting_claim_ids", "claim_ids"),
                    "evidence_ids": _first_list(raw, "evidence_ids", "supporting_evidence_ids", "evidence_refs"),
                }
            )
        raw_decisions = _first_list(data, "decision_cards", "decisions", "rd_decision_cards", "recommendations")
        decisions = []
        for raw in raw_decisions:
            if hasattr(raw, "model_dump"):
                raw = raw.model_dump()
            if not isinstance(raw, dict):
                continue
            title = _first_text(raw, "title_zh", "title")
            next_experiment = _first_text(
                raw, "next_experiment_zh", "next_experiment", "experiment_design_zh", "experiment_design",
            )
            evidence_ids = _first_list(raw, "evidence_ids", "supporting_evidence_ids", "evidence_refs")
            if not title or not next_experiment:
                continue
            decisions.append(
                {
                    "title_zh": title,
                    "recommendation_zh": _first_text(
                        raw, "recommendation_zh", "recommendation", "priority_action_zh", "action_zh",
                        "decision_zh", "experiment_design_zh",
                    ),
                    "rationale_zh": _first_text(
                        raw, "rationale_zh", "rationale", "justification_zh", "expected_outcome_zh",
                        "context_zh", "objective_zh",
                    ),
                    "next_experiment_zh": next_experiment,
                    "risks_zh": _first_list(raw, "risks_zh", "risk_and_mitigation_zh", "risks"),
                    "confidence": raw.get("confidence", 0.65),
                    "evidence_ids": evidence_ids,
                }
            )
        data["insights"] = insights
        data["decision_cards"] = decisions
        return data


def _confidence(value) -> float:
    if isinstance(value, (int, float)):
        return max(0.0, min(1.0, float(value)))
    text = str(value).strip().lower()
    labels = {"高": 0.85, "high": 0.85, "中": 0.65, "medium": 0.65, "低": 0.4, "low": 0.4}
    if text in labels:
        return labels[text]
    try:
        number = float(text.rstrip("%"))
        if text.endswith("%") or number > 1:
            number /= 100
        return max(0.0, min(1.0, number))
    except ValueError:
        return 0.6


def _insight_type(value) -> str:
    text = str(value or "").strip()
    return {
        "一致证据": "agreement", "一致": "agreement", "consistent_evidence": "agreement",
        "证据矛盾": "contradiction", "矛盾": "contradiction", "conflicting_evidence": "contradiction",
        "研究空白": "research_gap", "空白": "research_gap", "research_gap": "research_gap",
        "迁移机会": "transfer_opportunity", "技术迁移": "transfer_opportunity", "技术迁移机会": "transfer_opportunity",
        "technology_transfer": "transfer_opportunity", "technology_transfer_opportunity": "transfer_opportunity",
        "技术演进": "technical_lineage", "技术演进关系": "technical_lineage", "技术谱系": "technical_lineage",
        "technology_evolution": "technical_lineage", "technical_lineage": "technical_lineage",
        "agreement": "agreement", "contradiction": "contradiction", "transfer_opportunity": "transfer_opportunity",
    }.get(text, "research_gap")


def _first_text(value: dict, *keys: str) -> str:
    for key in keys:
        item = value.get(key)
        if item is not None and str(item).strip():
            return str(item).strip()
    return ""


def _first_list(value: dict, *keys: str) -> list:
    for key in keys:
        item = value.get(key)
        if item is None or item == "":
            continue
        return item if isinstance(item, list) else [item]
    return []
