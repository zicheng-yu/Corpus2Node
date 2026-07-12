#!/usr/bin/env python3
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
from pathlib import Path
from typing import Any

from pypdf import PdfReader

from corpus2node.llm import factory
from corpus2node.llm.credentials import Purpose
from corpus2node.llm.structured import make_structured
from corpus2node.scientific.prompts import PAPER_EXTRACTION_SYSTEM_PROMPT
from corpus2node.scientific.schemas import LLMPaperExtraction, ScientificEntityType, ScientificRelation

KEYWORDS = (
    "abstract", "introduction", "method", "approach", "experiment", "evaluation", "result",
    "discussion", "conclusion", "limitation", "摘要", "引言", "方法", "实验", "结果", "结论", "局限",
)


def selected_pages(pdf_path: str | Path, *, max_pages: int = 8, max_chars: int = 18_000) -> list[tuple[str, int, str]]:
    reader = PdfReader(str(pdf_path))
    pages = [(index + 1, (page.extract_text() or "").strip()) for index, page in enumerate(reader.pages)]
    scored = []
    for index, text in pages:
        lowered = text[:2400].lower()
        score = sum(2 for value in KEYWORDS if value in lowered)
        if index <= 2 or index > len(pages) - 2:
            score += 3
        scored.append((score, index, text))
    chosen = sorted(sorted(scored, key=lambda value: (-value[0], value[1]))[:max_pages], key=lambda value: value[1])
    result = []
    used = 0
    for _, page, text in chosen:
        if not text or used >= max_chars:
            continue
        text = " ".join(text.split())[: max_chars - used]
        result.append((f"P{page:03d}", page, text))
        used += len(text)
    return result


def build_prompt(record: dict[str, Any], pages: list[tuple[str, int, str]]) -> str:
    lines = [
        f"论文标题：{record['title']}",
        f"会议：{record['venue']} {record['year']}",
        "请生成科研证据预标注。只使用下面真实页码证据编号；每条实体、关系、主张、实验和数值都必须引用 Pxxx。",
        "正文说明一律中文，正式英文专名保留在独立字段。",
        "",
    ]
    lines.extend(f"[{alias}] PDF 第 {page} 页 | {text}" for alias, page, text in pages)
    return "\n".join(lines)


def extraction_to_gold(record: dict[str, Any], raw: LLMPaperExtraction, pages: list[tuple[str, int, str]]) -> dict:
    page_by_alias = {alias: page for alias, page, _ in pages}
    paper_key = record["paper_id"]

    def identifier(kind: str, value: str) -> str:
        digest = hashlib.sha1(f"{paper_key}:{kind}:{value}".encode()).hexdigest()[:12]
        return f"{kind}-{digest}"

    def evidence_ids(values: list[str]) -> list[str]:
        normalized = [value.strip().strip("[]").upper() for value in values]
        return list(dict.fromkeys(value for value in normalized if value in page_by_alias))

    entities = []
    for value in raw.entities:
        refs = evidence_ids(value.evidence_ids)
        name = value.name_en or value.name_zh
        if not refs or not name:
            continue
        raw_type = value.entity_type.strip().lower()
        entity_type = raw_type if raw_type in {item.value for item in ScientificEntityType} else "model"
        entities.append({"annotation_id": identifier("entity", name), "entity_type": entity_type, "text": name})
    relations = []
    for value in raw.relations:
        refs = evidence_ids(value.evidence_ids)
        if not refs or not value.source_name or not value.target_name:
            continue
        relation_type = ScientificRelation.model_validate(
            {
                "session_id": "00000000-0000-0000-0000-000000000000",
                "source_name": value.source_name,
                "relation_type": value.relation_type,
                "target_name": value.target_name,
            }
        ).relation_type.value
        relations.append(
            {
                "annotation_id": identifier("relation", f"{value.source_name}:{relation_type}:{value.target_name}"),
                "relation_type": relation_type,
                "roles": {"source": [value.source_name], "target": [value.target_name], "evidence": refs},
            }
        )
    claims = []
    for value in raw.claims:
        refs = evidence_ids(value.evidence_ids)
        if refs and value.statement_zh:
            claims.append(
                {
                    "annotation_id": identifier("claim", value.statement_zh),
                    "text": value.statement_zh,
                    "evidence_ids": refs,
                }
            )
    numeric_results = []
    for experiment in raw.experiments:
        experiment_refs = evidence_ids(experiment.evidence_ids)
        for metric in experiment.metrics:
            refs = evidence_ids(metric.evidence_ids) or experiment_refs
            if not refs or not metric.metric_name or not metric.value:
                continue
            numeric_results.append(
                {
                    "annotation_id": identifier("numeric", f"{metric.metric_name}:{metric.value}:{experiment.conditions_zh}"),
                    "metric": metric.metric_name,
                    "value": metric.value,
                    "unit": metric.unit,
                    "condition": experiment.conditions_zh,
                    "evidence_ids": refs,
                }
            )
        if experiment.methods and experiment.datasets_or_environments and experiment_refs:
            roles = {
                "experiment": [experiment.name_zh], "method": experiment.methods,
                "dataset": experiment.datasets_or_environments, "condition": [experiment.conditions_zh],
                "evidence": experiment_refs,
            }
            relations.append(
                {
                    "annotation_id": identifier("relation", json.dumps(roles, ensure_ascii=False, sort_keys=True)),
                    "relation_type": "EVALUATED_ON",
                    "roles": roles,
                }
            )
        if experiment.methods and experiment.baselines and experiment.metrics and experiment_refs:
            comparison = " ".join([experiment.conclusion_zh] + [value.comparison_zh for value in experiment.metrics]).lower()
            if any(value in comparison for value in ("优于", "超过", "提升", "outperform", "better", "improve")):
                roles = {
                    "experiment": [experiment.name_zh], "method": experiment.methods,
                    "baseline": experiment.baselines,
                    "metric": [value.metric_name for value in experiment.metrics],
                    "condition": [experiment.conditions_zh], "evidence": experiment_refs,
                }
                relations.append(
                    {
                        "annotation_id": identifier("relation", json.dumps(roles, ensure_ascii=False, sort_keys=True)),
                        "relation_type": "OUTPERFORMS",
                        "roles": roles,
                    }
                )
    referenced = {ref for value in claims for ref in value["evidence_ids"]}
    referenced |= {ref for value in numeric_results for ref in value["evidence_ids"]}
    referenced |= {ref for value in relations for ref in value["roles"].get("evidence", [])}
    locators = [
        {
            "evidence_id": alias, "section_path": [], "sentence_id": "", "page": page,
            "bboxes": [], "table_id": "", "table_row": None, "table_column": None,
        }
        for alias, page, _ in pages if alias in referenced
    ]
    return {
        "schema_version": "1.0",
        "paper_id": paper_key,
        "title": record["title"],
        "venue": record["venue"],
        "year": record["year"],
        "pdf_path": record.get("selected_pdf", record.get("local_pdf", "")),
        "review_status": "silver",
        "annotators": ["Corpus2Node automatic preannotation; human verification required"],
        "entities": entities,
        "relations": relations,
        "claims": claims,
        "numeric_results": numeric_results,
        "locators": locators,
    }


async def run(root: Path, *, concurrency: int = 3) -> None:
    records = json.loads((root / "metadata" / "selected-30.json").read_text(encoding="utf-8"))
    model = factory.build_chat_model(Purpose.graph)
    caller = make_structured(
        model,
        LLMPaperExtraction,
        system=PAPER_EXTRACTION_SYSTEM_PROMPT,
        method=factory.structured_output_method(Purpose.graph),
    )
    semaphore = asyncio.Semaphore(concurrency)
    gold_dir = root / "gold" / "selected-corpus-30-annotations"

    async def one(index: int, record: dict[str, Any]) -> None:
        target = gold_dir / f"{Path(record['selected_pdf']).stem}.json"
        if target.exists():
            status = json.loads(target.read_text(encoding="utf-8")).get("review_status")
            if status in {"silver", "verified"}:
                return
        pages = await asyncio.to_thread(selected_pages, record["selected_pdf"])
        async with semaphore:
            print(f"Preannotation {index}/{len(records)}: {record['title'][:70]}", flush=True)
            last_error: Exception | None = None
            for attempt in range(2):
                try:
                    raw = await caller(build_prompt(record, pages))
                    break
                except Exception as exc:
                    last_error = exc
                    if attempt == 0:
                        await asyncio.sleep(2)
            else:
                assert last_error is not None
                raise last_error
        target.write_text(
            json.dumps(extraction_to_gold(record, raw, pages), ensure_ascii=False, indent=2), encoding="utf-8"
        )

    results = await asyncio.gather(
        *(one(index, record) for index, record in enumerate(records, start=1)),
        return_exceptions=True,
    )
    failures = [str(value) for value in results if isinstance(value, Exception)]
    (root / "metadata" / "preannotation-errors.json").write_text(
        json.dumps(failures, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"Completed: {len(records) - len(failures)}; failed: {len(failures)}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path.home() / "Desktop" / "marl-top3-2024-2025")
    parser.add_argument("--concurrency", type=int, default=3)
    args = parser.parse_args()
    asyncio.run(run(args.root.expanduser(), concurrency=max(1, args.concurrency)))


if __name__ == "__main__":
    main()
