"""Minimal PDF adapter via Kimi's Files API (file-extract).

Minimal on purpose — PPT/Word/Markdown/image (multimodal) adapters and a proper
upload route are a planned follow-up batch. Returns page-ish text blocks; the
chunker turns those into EvidenceChunks (page index preserved as a locator).
"""
from __future__ import annotations

import json
import re
import time
from pathlib import Path

from corpus2node.config import settings
from corpus2node.core.text import normalize_text

_PAGE_MARKER = re.compile(
    r"(?im)^\s*(?:#{1,6}\s*)?(?:-{2,}\s*)?(?:page|p\.|第)\s*(\d{1,4})\s*(?:页)?\s*[:：]?\s*(?:-{2,})?\s*$"
)


def kimi_pdf_configured() -> bool:
    return bool(settings.kimi_api_key and settings.kimi_model)


def extract_pdf_blocks(filename: str, pdf_path: str | Path) -> list[str]:
    """Extract a PDF into page-ish text blocks via Kimi."""
    if not kimi_pdf_configured():
        raise RuntimeError("Kimi PDF extraction is not configured. Set KIMI_API_KEY and KIMI_MODEL.")
    raw = _kimi_extract_file_content(pdf_path)
    blocks = [block for block in _split_into_blocks(raw) if normalize_text(block)]
    if not blocks:
        raise RuntimeError(f"Kimi PDF extraction returned no usable text for {filename}.")
    return blocks


def _kimi_client():
    try:
        from openai import OpenAI
    except ImportError as exc:
        raise RuntimeError("PDF ingest needs the `ml` extra (openai): run `uv sync --extra ml`.") from exc

    kwargs: dict[str, object] = {"api_key": settings.kimi_api_key, "timeout": settings.kimi_timeout_seconds}
    if settings.kimi_base_url:
        kwargs["base_url"] = settings.kimi_base_url
    return OpenAI(**kwargs)


def _kimi_extract_file_content(pdf_path: str | Path) -> str:
    client = _kimi_client()
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
