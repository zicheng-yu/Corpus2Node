#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import random
from datetime import datetime, timezone
from pathlib import Path

from corpus2node.scientific.evaluation import (
    GoldReviewStatus,
    evaluate_gold_corpus,
    evaluate_paper,
    load_gold_directory,
)


def _verify_manifest(path: Path, *, reference: bool = False) -> tuple[dict, str]:
    manifest_path = path / "MANIFEST.json"
    payload = manifest_path.read_bytes()
    manifest = json.loads(payload)
    if reference:
        if manifest.get("reference_type") != "ai_independent_blind_proxy":
            raise ValueError("reference manifest has the wrong reference_type")
        if manifest.get("human_domain_expert_reviewed") is not False:
            raise ValueError("AI proxy must not be marked as human reviewed")
        prompt_path = path / manifest.get("prompt_file", "")
        if not prompt_path.is_file():
            raise ValueError("reference prompt artifact is missing")
        if hashlib.sha256(prompt_path.read_bytes()).hexdigest() != manifest.get("prompt_sha256"):
            raise ValueError("reference prompt artifact changed")
    elif not manifest.get("immutable_prediction_snapshot"):
        raise ValueError("prediction snapshot is not marked immutable")
    expected_names = {value["file"] for value in manifest["files"]}
    actual_names = {value.name for value in path.glob("*.json") if value.name != "MANIFEST.json"}
    if manifest.get("paper_count") != len(expected_names) or actual_names != expected_names:
        raise ValueError(f"manifest file set does not match directory: {path}")
    for value in manifest["files"]:
        candidate = path / value["file"]
        file_payload = candidate.read_bytes()
        digest = hashlib.sha256(file_payload).hexdigest()
        if digest != value["sha256"]:
            raise ValueError(f"manifest-protected file changed: {candidate.name}")
        if value.get("bytes") != len(file_payload):
            raise ValueError(f"manifest byte count changed: {candidate.name}")
        if reference:
            source_pdf = Path(value.get("source_pdf", ""))
            if not source_pdf.is_file():
                raise ValueError(f"reference source PDF is missing: {candidate.name}")
            if hashlib.sha256(source_pdf.read_bytes()).hexdigest() != value.get("source_pdf_sha256"):
                raise ValueError(f"reference source PDF changed: {source_pdf.name}")
    return manifest, hashlib.sha256(payload).hexdigest()


def _bootstrap(values: list[float], *, samples: int = 5000) -> dict[str, float]:
    if not values:
        return {"mean": 0.0, "ci95_low": 0.0, "ci95_high": 0.0}
    rng = random.Random(20260713)
    means = sorted(sum(rng.choice(values) for _ in values) / len(values) for _ in range(samples))
    return {
        "mean": sum(values) / len(values),
        "ci95_low": means[int(samples * 0.025)],
        "ci95_high": means[min(samples - 1, int(samples * 0.975))],
    }


def run(gold_dir: Path, prediction_dir: Path, output_dir: Path) -> dict:
    prediction_manifest, prediction_manifest_sha256 = _verify_manifest(prediction_dir)
    reference_manifest, reference_manifest_sha256 = _verify_manifest(gold_dir, reference=True)
    gold = load_gold_directory(gold_dir)
    predictions = {value.paper_id: value for value in load_gold_directory(prediction_dir)}
    if len(gold) != 30 or any(value.review_status != GoldReviewStatus.ai_verified for value in gold):
        raise ValueError("AI proxy benchmark requires exactly 30 ai_verified reference papers")
    if set(predictions) != {value.paper_id for value in gold}:
        raise ValueError("prediction and gold paper ids do not match")
    aggregate = evaluate_gold_corpus(
        gold_dir,
        prediction_dir,
        accepted_statuses={GoldReviewStatus.ai_verified},
    )
    per_paper = [evaluate_paper(value, predictions[value.paper_id]) for value in gold]
    def metric_values(name: str) -> list[float]:
        return [getattr(value, name).f1 for value in per_paper if getattr(value, name).gold]

    macro = {
        "entity_f1": _bootstrap(metric_values("entity")),
        "relation_f1": _bootstrap(metric_values("relation")),
        "claim_f1": _bootstrap(metric_values("claim")),
        "claim_exact_f1": _bootstrap(metric_values("claim_exact")),
        "numeric_f1": _bootstrap(metric_values("numeric_result")),
        "locator_exact_accuracy": _bootstrap(
            [value.locator_exact_accuracy for value in per_paper if value.locator_count]
        ),
        "locator_bbox_accuracy": _bootstrap(
            [value.locator_bbox_accuracy for value in per_paper if value.bbox_locator_count]
        ),
    }
    locators = [locator for paper in gold for locator in paper.locators]
    locator_scope = {
        "total": len(locators),
        "page_only": sum(
            bool(value.page) and not value.sentence_id and not value.table_id for value in locators
        ),
        "sentence_id": sum(bool(value.sentence_id) for value in locators),
        "table_cell": sum(bool(value.table_id) for value in locators),
        "section_path": sum(bool(value.section_path) for value in locators),
        "bbox": sum(bool(value.bboxes) for value in locators),
    }
    now = datetime.now(timezone.utc)
    result = {
        "date": now.date().isoformat(),
        "generated_at": now.isoformat(),
        "evaluation_type": "ai_independent_blind_proxy",
        "human_domain_expert_reviewed": False,
        "scope": {
            "papers": 30,
            "venues": ["ICLR", "ICML", "NeurIPS"],
            "years": [2024, 2025],
            "prediction_snapshot": str(prediction_dir),
            "reference_directory": str(gold_dir),
        },
        "provenance": {
            "prediction_manifest_sha256": prediction_manifest_sha256,
            "reference_manifest_sha256": reference_manifest_sha256,
            "prediction_paper_count": prediction_manifest["paper_count"],
            "reference_paper_count": reference_manifest["paper_count"],
            "reference_prompt_artifact": reference_manifest["prompt_file"],
            "reference_prompt_sha256": reference_manifest["prompt_sha256"],
            "reference_source_pdf_hashes_verified": reference_manifest["paper_count"],
        },
        "aggregate_micro": aggregate.model_dump(mode="json"),
        "aggregate_macro_bootstrap": macro,
        "locator_scope": locator_scope,
        "metric_notes": {
            "entity": "typed normalized-string exact match",
            "relation": "relation type plus complete normalized role-set exact match",
            "claim": "heuristic character similarity >= 0.45 plus shared page/table evidence id",
            "claim_exact": "normalized full-text exact match",
            "numeric": "metric, Decimal-normalized value, unit, and free-text condition exact match",
            "locator": "key/bbox-set agreement; most references are page-level, not claim-level sentences",
            "bootstrap": "paper-level resampling interval, not model-run or multi-seed uncertainty",
        },
        "per_paper": [value.model_dump(mode="json") for value in per_paper],
        "interpretation_limit": (
            "Reference annotations were generated by a blind AI pass reusing the same schema and page-selection "
            "pipeline, followed by deterministic evidence-id checks. Scores measure agreement with this correlated "
            "AI proxy, not human-expert accuracy. Locator scores are mostly page-level agreement."
        ),
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    stamp = result["date"]
    (output_dir / f"formal-evaluation-{stamp}.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    lines = [
        "# Scientific Evidence Benchmark",
        "",
        "- Evaluation type: AI independent blind proxy",
        "- Human domain-expert reviewed: no",
        "- Papers: 30 (ICLR/ICML/NeurIPS, 2024-2025)",
        "",
        "| Metric | Micro P | Micro R | Micro F1 | Macro mean | 95% bootstrap CI |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for label, field, macro_key in (
        ("Entity", aggregate.entity, "entity_f1"),
        ("Relation", aggregate.relation, "relation_f1"),
        ("Claim", aggregate.claim, "claim_f1"),
        ("Claim exact", aggregate.claim_exact, "claim_exact_f1"),
        ("Numeric", aggregate.numeric_result, "numeric_f1"),
    ):
        interval = macro[macro_key]
        lines.append(
            f"| {label} | {field.precision:.4f} | {field.recall:.4f} | {field.f1:.4f} | "
            f"{interval['mean']:.4f} | [{interval['ci95_low']:.4f}, {interval['ci95_high']:.4f}] |"
        )
    lines.extend(
        [
            "",
            f"- Locator key agreement: {aggregate.locator_exact_accuracy:.4f} ({aggregate.locator_count} reference locators)",
            f"- GROBID-derived bbox-set agreement: {aggregate.locator_bbox_accuracy:.4f} ({aggregate.bbox_locator_count} bbox locators)",
            f"- Locator scope: {locator_scope['page_only']} page-only / {locator_scope['sentence_id']} sentence-id / {locator_scope['table_cell']} table-cell",
            "",
            "> Limitation: this is a correlated AI-proxy internal benchmark, not a human-expert gold benchmark. "
            "Locator scores are mostly page-level reproducibility, not claim-level sentence grounding accuracy.",
        ]
    )
    (output_dir / f"formal-evaluation-{stamp}.md").write_text(
        "\n".join(lines) + "\n", encoding="utf-8"
    )
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    root = Path.home() / "Desktop" / "marl-top3-2024-2025"
    parser.add_argument("--gold-dir", type=Path, default=root / "gold" / "verified-codex-annotations")
    parser.add_argument("--prediction-dir", type=Path, default=root / "predictions" / "silver-baseline-2026-07-13")
    parser.add_argument("--output-dir", type=Path, default=root / "results")
    args = parser.parse_args()
    result = run(args.gold_dir.expanduser(), args.prediction_dir.expanduser(), args.output_dir.expanduser())
    print(json.dumps(result["aggregate_micro"], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
