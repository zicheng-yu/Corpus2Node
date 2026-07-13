from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation
from difflib import SequenceMatcher
from enum import Enum
from pathlib import Path

from pydantic import BaseModel, Field

from corpus2node.scientific.schemas import ScientificBBox, ScientificEntityType, ScientificRelationType


class GoldReviewStatus(str, Enum):
    unreviewed = "unreviewed"
    silver = "silver"
    ai_verified = "ai_verified"
    verified = "verified"


class GoldEntity(BaseModel):
    annotation_id: str
    entity_type: ScientificEntityType
    text: str


class GoldRelation(BaseModel):
    annotation_id: str
    relation_type: ScientificRelationType
    roles: dict[str, list[str]] = Field(default_factory=dict)


class GoldClaim(BaseModel):
    annotation_id: str
    text: str
    evidence_ids: list[str] = Field(default_factory=list)


class GoldNumericResult(BaseModel):
    annotation_id: str
    metric: str
    value: str
    unit: str = ""
    condition: str = ""
    evidence_ids: list[str] = Field(default_factory=list)


class GoldLocator(BaseModel):
    evidence_id: str
    section_path: list[str] = Field(default_factory=list)
    sentence_id: str = ""
    page: int | None = None
    bboxes: list[ScientificBBox] = Field(default_factory=list)
    table_id: str = ""
    table_row: int | None = None
    table_column: int | None = None


class ScientificGoldPaper(BaseModel):
    schema_version: str = "1.0"
    paper_id: str
    title: str
    venue: str
    year: int
    pdf_path: str
    review_status: GoldReviewStatus = GoldReviewStatus.unreviewed
    annotators: list[str] = Field(default_factory=list)
    entities: list[GoldEntity] = Field(default_factory=list)
    relations: list[GoldRelation] = Field(default_factory=list)
    claims: list[GoldClaim] = Field(default_factory=list)
    numeric_results: list[GoldNumericResult] = Field(default_factory=list)
    locators: list[GoldLocator] = Field(default_factory=list)


class PRF(BaseModel):
    true_positive: int
    predicted: int
    gold: int
    precision: float
    recall: float
    f1: float


class ScientificEvaluationResult(BaseModel):
    evaluated_papers: int
    skipped_unverified_papers: int
    entity: PRF
    relation: PRF
    claim: PRF
    claim_exact: PRF
    numeric_result: PRF
    locator_exact_accuracy: float
    locator_bbox_accuracy: float
    locator_count: int
    bbox_locator_count: int


class ScientificPaperEvaluation(BaseModel):
    paper_id: str
    title: str
    entity: PRF
    relation: PRF
    claim: PRF
    claim_exact: PRF
    numeric_result: PRF
    locator_exact_accuracy: float
    locator_bbox_accuracy: float
    locator_count: int
    bbox_locator_count: int


def evaluate_gold_corpus(
    gold_dir: str | Path,
    prediction_dir: str | Path,
    *,
    require_verified: bool = True,
    accepted_statuses: set[GoldReviewStatus] | None = None,
) -> ScientificEvaluationResult:
    gold_papers = _load_papers(gold_dir)
    predictions = {value.paper_id: value for value in _load_papers(prediction_dir)}
    allowed = accepted_statuses or {GoldReviewStatus.verified}
    counts = {name: [0, 0, 0] for name in ("entity", "relation", "claim", "claim_exact", "numeric")}
    exact_locator = bbox_locator = locator_count = bbox_locator_count = evaluated = skipped = 0
    for gold in gold_papers:
        if require_verified and gold.review_status not in allowed:
            skipped += 1
            continue
        evaluated += 1
        prediction = predictions.get(
            gold.paper_id,
            ScientificGoldPaper(
                paper_id=gold.paper_id,
                title=gold.title,
                venue=gold.venue,
                year=gold.year,
                pdf_path=gold.pdf_path,
            ),
        )
        _accumulate(counts["entity"], _entity_keys(gold), _entity_keys(prediction))
        _accumulate(counts["relation"], _relation_keys(gold), _relation_keys(prediction))
        claim_matches = _claim_match_count(gold.claims, prediction.claims)
        counts["claim"][0] += claim_matches
        counts["claim"][1] += len(prediction.claims)
        counts["claim"][2] += len(gold.claims)
        _accumulate(counts["claim_exact"], _claim_keys(gold), _claim_keys(prediction))
        _accumulate(counts["numeric"], _numeric_keys(gold), _numeric_keys(prediction))
        predicted_locators = {value.evidence_id: value for value in prediction.locators}
        for locator in gold.locators:
            locator_count += 1
            if locator.bboxes:
                bbox_locator_count += 1
            candidate = predicted_locators.get(locator.evidence_id)
            if candidate is None:
                continue
            if _locator_key(locator) == _locator_key(candidate):
                exact_locator += 1
            if locator.bboxes:
                if _bbox_match(locator.bboxes, candidate.bboxes):
                    bbox_locator += 1
    if require_verified and evaluated == 0:
        expected = ", ".join(sorted(value.value for value in allowed))
        raise ValueError(f"没有 review_status in {{{expected}}} 的参考标注，拒绝输出指标。")
    return ScientificEvaluationResult(
        evaluated_papers=evaluated,
        skipped_unverified_papers=skipped,
        entity=_prf(*counts["entity"]),
        relation=_prf(*counts["relation"]),
        claim=_prf(*counts["claim"]),
        claim_exact=_prf(*counts["claim_exact"]),
        numeric_result=_prf(*counts["numeric"]),
        locator_exact_accuracy=exact_locator / locator_count if locator_count else 0.0,
        locator_bbox_accuracy=bbox_locator / bbox_locator_count if bbox_locator_count else 0.0,
        locator_count=locator_count,
        bbox_locator_count=bbox_locator_count,
    )


def evaluate_paper(gold: ScientificGoldPaper, prediction: ScientificGoldPaper) -> ScientificPaperEvaluation:
    counts = {}
    for name, gold_keys, prediction_keys in (
        ("entity", _entity_keys(gold), _entity_keys(prediction)),
        ("relation", _relation_keys(gold), _relation_keys(prediction)),
        ("claim_exact", _claim_keys(gold), _claim_keys(prediction)),
        ("numeric", _numeric_keys(gold), _numeric_keys(prediction)),
    ):
        counts[name] = _prf(len(gold_keys & prediction_keys), len(prediction_keys), len(gold_keys))
    predicted_locators = {value.evidence_id: value for value in prediction.locators}
    claim = _prf(_claim_match_count(gold.claims, prediction.claims), len(prediction.claims), len(gold.claims))
    exact = bbox = bbox_count = 0
    for locator in gold.locators:
        candidate = predicted_locators.get(locator.evidence_id)
        if locator.bboxes:
            bbox_count += 1
        if candidate is None:
            continue
        if _locator_key(locator) == _locator_key(candidate):
            exact += 1
        if locator.bboxes and _bbox_match(locator.bboxes, candidate.bboxes):
            bbox += 1
    return ScientificPaperEvaluation(
        paper_id=gold.paper_id,
        title=gold.title,
        entity=counts["entity"],
        relation=counts["relation"],
        claim=claim,
        claim_exact=counts["claim_exact"],
        numeric_result=counts["numeric"],
        locator_exact_accuracy=exact / len(gold.locators) if gold.locators else 0.0,
        locator_bbox_accuracy=bbox / bbox_count if bbox_count else 0.0,
        locator_count=len(gold.locators),
        bbox_locator_count=bbox_count,
    )


def load_gold_directory(path: str | Path) -> list[ScientificGoldPaper]:
    return _load_papers(path)


def _load_papers(path: str | Path) -> list[ScientificGoldPaper]:
    papers = []
    for candidate in sorted(Path(path).glob("*.json")):
        if candidate.name == "MANIFEST.json":
            continue
        papers.append(ScientificGoldPaper.model_validate_json(candidate.read_text(encoding="utf-8")))
    return papers


def write_gold_template(record: dict, target: str | Path) -> Path:
    path = Path(target)
    path.parent.mkdir(parents=True, exist_ok=True)
    paper = ScientificGoldPaper(
        paper_id=record["paper_id"],
        title=record["title"],
        venue=record["venue"],
        year=record["year"],
        pdf_path=record.get("local_pdf", ""),
    )
    path.write_text(paper.model_dump_json(indent=2), encoding="utf-8")
    return path


def _normalize(value: str) -> str:
    return re.sub(r"\W+", " ", value.casefold()).strip()


def _entity_keys(value: ScientificGoldPaper) -> set[tuple]:
    return {(item.entity_type.value, _normalize(item.text)) for item in value.entities}


def _relation_keys(value: ScientificGoldPaper) -> set[tuple]:
    return {
        (
            item.relation_type.value,
            tuple(sorted((role, tuple(sorted(_normalize(value) for value in values))) for role, values in item.roles.items())),
        )
        for item in value.relations
    }


def _claim_keys(value: ScientificGoldPaper) -> set[str]:
    return {_normalize(item.text) for item in value.claims}


def _claim_match_count(gold: list[GoldClaim], predicted: list[GoldClaim]) -> int:
    candidates = []
    for gold_index, left in enumerate(gold):
        left_evidence = set(left.evidence_ids)
        for predicted_index, right in enumerate(predicted):
            if left_evidence and not left_evidence.intersection(right.evidence_ids):
                continue
            score = _claim_similarity(left.text, right.text)
            if score >= 0.45:
                candidates.append((score, gold_index, predicted_index))
    matched_gold: set[int] = set()
    matched_predicted: set[int] = set()
    for _, gold_index, predicted_index in sorted(candidates, reverse=True):
        if gold_index in matched_gold or predicted_index in matched_predicted:
            continue
        matched_gold.add(gold_index)
        matched_predicted.add(predicted_index)
    return len(matched_gold)


def _claim_similarity(left: str, right: str) -> float:
    left_text = re.sub(r"\W+", "", left.casefold())
    right_text = re.sub(r"\W+", "", right.casefold())
    if not left_text or not right_text:
        return 0.0
    left_bigrams = {left_text[index:index + 2] for index in range(max(1, len(left_text) - 1))}
    right_bigrams = {right_text[index:index + 2] for index in range(max(1, len(right_text) - 1))}
    dice = 2 * len(left_bigrams & right_bigrams) / (len(left_bigrams) + len(right_bigrams))
    sequence = SequenceMatcher(None, left_text, right_text).ratio()
    return max(dice, sequence)


def _number(value: str) -> str:
    try:
        return str(Decimal(value.replace(",", "")).normalize())
    except InvalidOperation:
        return _normalize(value)


def _numeric_keys(value: ScientificGoldPaper) -> set[tuple]:
    return {
        (_normalize(item.metric), _number(item.value), _normalize(item.unit), _normalize(item.condition))
        for item in value.numeric_results
    }


def _locator_key(value: GoldLocator) -> tuple:
    return (
        tuple(_normalize(item) for item in value.section_path),
        value.sentence_id,
        value.page,
        value.table_id,
        value.table_row,
        value.table_column,
    )


def _bbox_match(gold: list[ScientificBBox], predicted: list[ScientificBBox]) -> bool:
    if not gold:
        return not predicted
    return all(any(_iou(left, right) >= 0.8 for right in predicted) for left in gold)


def _iou(left: ScientificBBox, right: ScientificBBox) -> float:
    if left.page != right.page:
        return 0.0
    x1, y1 = max(left.x, right.x), max(left.y, right.y)
    x2 = min(left.x + left.width, right.x + right.width)
    y2 = min(left.y + left.height, right.y + right.height)
    intersection = max(0.0, x2 - x1) * max(0.0, y2 - y1)
    union = left.width * left.height + right.width * right.height - intersection
    return intersection / union if union else 0.0


def _accumulate(counts: list[int], gold: set, predicted: set) -> None:
    counts[0] += len(gold & predicted)
    counts[1] += len(predicted)
    counts[2] += len(gold)


def _prf(true_positive: int, predicted: int, gold: int) -> PRF:
    precision = true_positive / predicted if predicted else 0.0
    recall = true_positive / gold if gold else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    return PRF(
        true_positive=true_positive,
        predicted=predicted,
        gold=gold,
        precision=precision,
        recall=recall,
        f1=f1,
    )
