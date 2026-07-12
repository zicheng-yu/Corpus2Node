#!/usr/bin/env python3
from __future__ import annotations

import argparse
import asyncio
import json
import re
from pathlib import Path
from typing import Any

from corpus2node.scientific.parsers import parse_tei_xml, request_grobid_tei


def _slug(record: dict[str, Any]) -> str:
    return Path(record["selected_pdf"]).stem


def _page_alias(value: str) -> int | None:
    match = re.fullmatch(r"P(\d+)", value)
    return int(match.group(1)) if match else None


def _enrich_annotation(path: Path, document) -> None:
    annotation = json.loads(path.read_text(encoding="utf-8"))
    locators = {value["evidence_id"]: value for value in annotation.get("locators", [])}
    page_boxes: dict[int, list[dict]] = {}
    page_sentences: dict[int, list[str]] = {}
    for section in document.sections:
        for sentence in section.sentences:
            locator = sentence.locator
            if locator.page:
                page_boxes.setdefault(locator.page, []).extend(value.model_dump() for value in locator.bboxes)
                page_sentences.setdefault(locator.page, []).append(sentence.sentence_id)
    for evidence_id, locator in locators.items():
        page = _page_alias(evidence_id)
        if not page:
            continue
        locator["page"] = page
        locator["bboxes"] = page_boxes.get(page, [])
        sentence_ids = page_sentences.get(page, [])
        locator["sentence_id"] = sentence_ids[0] if len(sentence_ids) == 1 else ""
    for result in annotation.get("numeric_results", []):
        value = str(result.get("value", "")).replace(",", "").strip()
        if not value:
            continue
        for evidence_id in list(result.get("evidence_ids", [])):
            page = _page_alias(evidence_id)
            if not page:
                continue
            match = next(
                (
                    cell for table in document.tables for cell in table.cells
                    if cell.locator.page == page and value in cell.text.replace(",", "")
                ),
                None,
            )
            if match is None:
                continue
            cell_evidence = f"{evidence_id}:{match.cell_id}"
            result["evidence_ids"] = [
                cell_evidence if current == evidence_id else current for current in result["evidence_ids"]
            ]
            locators[cell_evidence] = {
                "evidence_id": cell_evidence,
                "section_path": match.locator.section_path,
                "sentence_id": "",
                "page": match.locator.page,
                "bboxes": [value.model_dump() for value in match.locator.bboxes],
                "table_id": match.locator.table_id,
                "table_row": match.locator.table_row,
                "table_column": match.locator.table_column,
            }
    annotation["locators"] = list(locators.values())
    annotation["parser"] = {"name": "GROBID", "version": "0.9.0-crf", "source_format": "grobid_tei"}
    path.write_text(json.dumps(annotation, ensure_ascii=False, indent=2), encoding="utf-8")


def _stats(document) -> dict[str, int]:
    sentences = [sentence for section in document.sections for sentence in section.sentences]
    cells = [cell for table in document.tables for cell in table.cells]
    return {
        "sections": len(document.sections),
        "sentences": len(sentences),
        "sentence_bboxes": sum(len(value.locator.bboxes) for value in sentences),
        "tables": len(document.tables),
        "table_cells": len(cells),
        "table_cell_bboxes": sum(len(value.locator.bboxes) for value in cells),
        "formulas": len(document.formulas),
        "formula_bboxes": sum(len(value.locator.bboxes) for value in document.formulas),
    }


async def run(root: Path, *, base_url: str, concurrency: int, force: bool = False) -> list[dict[str, Any]]:
    records = json.loads((root / "metadata" / "selected-30.json").read_text(encoding="utf-8"))
    tei_dir = root / "grobid" / "tei"
    document_dir = root / "grobid" / "documents"
    annotation_dir = root / "gold" / "selected-corpus-30-annotations"
    tei_dir.mkdir(parents=True, exist_ok=True)
    document_dir.mkdir(parents=True, exist_ok=True)
    semaphore = asyncio.Semaphore(concurrency)

    async def one(index: int, record: dict[str, Any]) -> dict[str, Any]:
        slug = _slug(record)
        tei_path = tei_dir / f"{slug}.tei.xml"
        document_path = document_dir / f"{slug}.json"
        try:
            async with semaphore:
                print(f"GROBID {index}/{len(records)}: {record['title'][:68]}", flush=True)
                tei = (
                    tei_path.read_bytes()
                    if tei_path.exists() and not force
                    else await asyncio.to_thread(
                        request_grobid_tei, record["selected_pdf"], base_url=base_url
                    )
                )
            tei_path.write_bytes(tei)
            document = parse_tei_xml(tei, source_id=record["paper_id"], from_grobid=True)
            document_path.write_text(document.model_dump_json(indent=2), encoding="utf-8")
            annotation_path = annotation_dir / f"{slug}.json"
            if annotation_path.exists():
                _enrich_annotation(annotation_path, document)
            return {"paper_id": record["paper_id"], "title": record["title"], "ok": True, **_stats(document)}
        except Exception as exc:
            return {
                "paper_id": record["paper_id"], "title": record["title"], "ok": False,
                "error": f"{type(exc).__name__}: {exc}",
            }

    results = await asyncio.gather(
        *(one(index, record) for index, record in enumerate(records, start=1))
    )
    (root / "metadata" / "grobid-parse-report.json").write_text(
        json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"Parsed: {sum(value['ok'] for value in results)}/{len(results)}")
    return results


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path.home() / "Desktop" / "marl-top3-2024-2025")
    parser.add_argument("--base-url", default="http://127.0.0.1:8070")
    parser.add_argument("--concurrency", type=int, default=2)
    parser.add_argument("--force", action="store_true", help="Request fresh TEI instead of reusing saved responses.")
    args = parser.parse_args()
    asyncio.run(
        run(
            args.root.expanduser(), base_url=args.base_url,
            concurrency=max(1, args.concurrency), force=args.force,
        )
    )


if __name__ == "__main__":
    main()
