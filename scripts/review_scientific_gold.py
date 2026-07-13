#!/usr/bin/env python3
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

from corpus2node.llm import factory
from corpus2node.llm.credentials import Purpose
from corpus2node.llm.structured import make_structured
from corpus2node.scientific.prompts import PAPER_EXTRACTION_SYSTEM_PROMPT
from corpus2node.scientific.schemas import LLMPaperExtraction, ScientificDocument
from parse_scientific_corpus import _enrich_annotation
from preannotate_scientific_gold import build_prompt, extraction_to_gold, selected_pages

GOLD_REVIEW_SYSTEM = PAPER_EXTRACTION_SYSTEM_PROMPT.replace("C01", "P001").replace("Cxx", "Pxxx") + """\

独立 gold 盲标补充要求：
你是科研证据数据集的独立标注员。你没有看到任何待评测模型的预测，只能依据输入的论文原文页进行盲标。

标注要求：
1. 说明、Claim 和实验结论用简体中文；方法、模型、数据集和指标的正式名称保留英文。
2. 每个实体、关系、Claim、实验和数值必须引用输入中存在的 Pxxx 页证据；没有直接证据就不标。
3. 数值必须逐字来自原文，value 保留原值，unit 单独填写，不能换算或推测。
4. OUTPERFORMS 必须在同一实验中同时给出 method、baseline、metric、condition 和 evidence；否则只记录普通结果。
5. relation_type 只能使用 PROPOSES、EXTENDS、USES、EVALUATED_ON、MEASURED_BY、REPORTS_RESULT、OUTPERFORMS、SUPPORTS、CONTRADICTS、REPLICATES、LIMITED_BY、REQUIRES、DERIVED_FROM、RELATED_TO。
6. 优先标注能影响研发判断的核心方法、实验结果、理论结论和局限；不要标作者、章节名和泛背景词。
7. 不得使用常识、论文外知识或猜测补齐字段。只返回符合 schema 的 JSON object。
"""


def deterministic_adjudicate(annotation: dict) -> dict:
    valid_evidence = {value["evidence_id"] for value in annotation.get("locators", [])}

    def grounded(values: list[str]) -> list[str]:
        return list(dict.fromkeys(value for value in values if value in valid_evidence))

    for claim in annotation.get("claims", []):
        claim["evidence_ids"] = grounded(claim.get("evidence_ids", []))
    annotation["claims"] = [value for value in annotation.get("claims", []) if value["evidence_ids"]]
    for value in annotation.get("numeric_results", []):
        value["evidence_ids"] = grounded(value.get("evidence_ids", []))
    annotation["numeric_results"] = [
        value for value in annotation.get("numeric_results", [])
        if value["evidence_ids"] and value.get("metric") and value.get("value")
    ]
    valid_relations = []
    for relation in annotation.get("relations", []):
        roles = relation.get("roles", {})
        roles["evidence"] = grounded(roles.get("evidence", []))
        required = {
            "OUTPERFORMS": ("experiment", "method", "baseline", "metric", "condition", "evidence"),
            "EVALUATED_ON": ("experiment", "method", "dataset", "evidence"),
            "SUPPORTS": ("source", "target", "evidence"),
        }.get(relation.get("relation_type"), ("source", "target", "evidence"))
        if all(roles.get(name) for name in required):
            valid_relations.append(relation)
    annotation["relations"] = valid_relations
    return annotation


def write_reference_manifest(records: list[dict], output_dir: Path) -> Path:
    prompt_path = output_dir / "REFERENCE_PROMPT.txt"
    prompt_path.write_text(GOLD_REVIEW_SYSTEM, encoding="utf-8")
    files = []
    for record in records:
        name = f"{Path(record['selected_pdf']).stem}.json"
        candidate = output_dir / name
        if not candidate.exists():
            raise ValueError(f"missing reference annotation: {name}")
        payload = candidate.read_bytes()
        pdf_payload = Path(record["selected_pdf"]).read_bytes()
        files.append(
            {
                "file": name,
                "paper_id": record["paper_id"],
                "bytes": len(payload),
                "sha256": hashlib.sha256(payload).hexdigest(),
                "source_pdf": record["selected_pdf"],
                "source_pdf_sha256": hashlib.sha256(pdf_payload).hexdigest(),
            }
        )
    manifest = {
        "reference_type": "ai_independent_blind_proxy",
        "human_domain_expert_reviewed": False,
        "paper_count": len(files),
        "prompt_file": prompt_path.name,
        "prompt_sha256": hashlib.sha256(prompt_path.read_bytes()).hexdigest(),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "files": files,
    }
    target = output_dir / "MANIFEST.json"
    target.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return target


async def run(root: Path, *, concurrency: int = 3, request_timeout: float = 300.0) -> list[dict]:
    records = json.loads((root / "metadata" / "selected-30.json").read_text(encoding="utf-8"))
    output_dir = root / "gold" / "verified-codex-annotations"
    document_dir = root / "grobid" / "documents"
    output_dir.mkdir(parents=True, exist_ok=True)
    caller = make_structured(
        factory.build_chat_model(Purpose.critic),
        LLMPaperExtraction,
        system=GOLD_REVIEW_SYSTEM,
        method=factory.structured_output_method(Purpose.critic),
    )
    semaphore = asyncio.Semaphore(concurrency)

    async def one(index: int, record: dict) -> dict:
        slug = Path(record["selected_pdf"]).stem
        target = output_dir / f"{slug}.json"
        if target.exists():
            existing = json.loads(target.read_text(encoding="utf-8"))
            if (
                existing.get("review_status") == "ai_verified"
                and existing.get("entities") and existing.get("claims")
            ):
                return {"paper_id": record["paper_id"], "ok": True, "cached": True}
        pages = await asyncio.to_thread(selected_pages, record["selected_pdf"])
        prompt = build_prompt(record, pages).replace(
            "请生成科研证据预标注。", "请从原文独立完成科研 gold 标注。"
        )
        last_error: Exception | None = None
        for attempt in range(2):
            try:
                async with semaphore:
                    print(f"Gold review {index}/{len(records)}: {record['title'][:66]}", flush=True)
                    raw = await asyncio.wait_for(caller(prompt), timeout=request_timeout)
                break
            except Exception as exc:
                last_error = exc
                if attempt == 0:
                    await asyncio.sleep(2)
        else:
            assert last_error is not None
            return {
                "paper_id": record["paper_id"], "title": record["title"], "ok": False,
                "error": f"{type(last_error).__name__}: {last_error}",
            }
        annotation = extraction_to_gold(record, raw, pages)
        if not annotation["entities"] or not annotation["claims"]:
            return {
                "paper_id": record["paper_id"], "title": record["title"], "ok": False,
                "error": "empty entities or claims after evidence validation",
            }
        annotation["review_status"] = "ai_verified"
        annotation["annotators"] = [
            "DeepSeek blind evidence annotation",
            "Codex deterministic schema/evidence adjudication",
        ]
        annotation["review_method"] = "AI-independent-blind-pass; not human-domain-expert gold"
        target.write_text(json.dumps(annotation, ensure_ascii=False, indent=2), encoding="utf-8")
        document_path = document_dir / f"{slug}.json"
        if document_path.exists():
            document = ScientificDocument.model_validate_json(document_path.read_text(encoding="utf-8"))
            _enrich_annotation(target, document)
        value = deterministic_adjudicate(json.loads(target.read_text(encoding="utf-8")))
        if not value["entities"] or not value["claims"]:
            target.unlink(missing_ok=True)
            return {
                "paper_id": record["paper_id"], "title": record["title"], "ok": False,
                "error": "empty entities or grounded claims after adjudication",
            }
        target.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
        return {
            "paper_id": record["paper_id"], "title": record["title"], "ok": True,
            "entities": len(value["entities"]), "relations": len(value["relations"]),
            "claims": len(value["claims"]), "numeric_results": len(value["numeric_results"]),
            "locators": len(value["locators"]),
        }

    results = await asyncio.gather(
        *(one(index, record) for index, record in enumerate(records, start=1))
    )
    (root / "metadata" / "codex-gold-review-report.json").write_text(
        json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    if all(value["ok"] for value in results):
        write_reference_manifest(records, output_dir)
    print(f"AI verified: {sum(value['ok'] for value in results)}/{len(results)}")
    return results


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path.home() / "Desktop" / "marl-top3-2024-2025")
    parser.add_argument("--concurrency", type=int, default=3)
    parser.add_argument("--request-timeout", type=float, default=300.0)
    args = parser.parse_args()
    asyncio.run(
        run(
            args.root.expanduser(),
            concurrency=max(1, args.concurrency),
            request_timeout=max(1.0, args.request_timeout),
        )
    )


if __name__ == "__main__":
    main()
