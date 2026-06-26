"""PDF adapter via Kimi's Files API (file-extract).

Returns page-ish text blocks; the shared chunker turns those into EvidenceChunks
with page index preserved as a locator when blocks are paginated.
"""
from __future__ import annotations

import json
import re
import time
from pathlib import Path

from corpus2node.core.text import normalize_text
from corpus2node.ingest.kimi_client import vision_client

_PAGE_MARKER = re.compile(
    r"(?im)^\s*(?:#{1,6}\s*)?(?:-{2,}\s*)?(?:page|p\.|第)\s*(\d{1,4})\s*(?:页)?\s*[:：]?\s*(?:-{2,})?\s*$"
)


def extract_pdf_blocks(filename: str, pdf_path: str | Path) -> list[str]:
    """Extract a PDF into page-ish text blocks via Kimi (vision credential from the registry)."""
    raw = _kimi_extract_file_content(pdf_path)
    blocks = [block for block in _split_into_blocks(raw) if normalize_text(block)]
    if not blocks:
        raise RuntimeError(f"Kimi PDF extraction returned no usable text for {filename}.")
    return blocks


def _kimi_extract_file_content(pdf_path: str | Path) -> str:
    client, _model = vision_client()  # file-extract needs only the endpoint+key, not the model
    file_object = client.files.create(file=Path(pdf_path), purpose="file-extract")
    file_id = file_object.id
    try:
        for attempt in range(8):
            if attempt:
                time.sleep(min(1.5 * attempt, 6.0))
            try:
                content = client.files.content(file_id=file_id)
            except Exception:
                if attempt >= 7:
                    raise
                continue
            text = getattr(content, "text", None)
            if not text:
                raw = getattr(content, "content", None)
                if isinstance(raw, bytes):
                    text = raw.decode("utf-8", errors="replace")
                elif isinstance(raw, str):
                    text = raw
            if text and text.strip():
                return text
        raise RuntimeError("Kimi file extraction returned empty content.")
    finally:
        try:
            client.files.delete(file_id=file_id)
        except Exception:
            pass


def _split_into_blocks(text: str) -> list[str]:
    content = _unwrap_json_content(text).replace("\\r", "\n").replace("\\n", "\n").replace("\\t", "\t")
    if not normalize_text(content):
        return []
    markers = list(_PAGE_MARKER.finditer(content))
    if markers:
        blocks: list[str] = []
        for index, marker in enumerate(markers):
            start = marker.end()
            end = markers[index + 1].start() if index + 1 < len(markers) else len(content)
            segment = normalize_text(content[start:end])
            if segment:
                blocks.append(segment)
        if blocks:
            return blocks
    return [normalize_text(content)]


def _unwrap_json_content(text: str) -> str:
    candidate = text.strip()
    if candidate.startswith("```"):
        candidate = candidate.strip("`").strip()
        if candidate.startswith("json"):
            candidate = candidate[4:].strip()
    try:
        payload = json.loads(candidate)
    except (json.JSONDecodeError, ValueError):
        return text
    if isinstance(payload, dict):
        for key in ("content", "text", "markdown", "body"):
            value = payload.get(key)
            if isinstance(value, str) and value.strip():
                return value
    return text
