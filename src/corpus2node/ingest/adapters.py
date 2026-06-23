"""Per-format ingest adapters: file -> list of text blocks.

A single registry keyed by extension; each adapter returns text blocks that the
shared chunker turns into EvidenceChunks. Heavy/optional parsers are imported
lazily so a missing one gives a clear message. Image/audio adapters are added in
a follow-up (they need a model/ASR decision); they're recognised by `kind_for`
but not yet extractable.
"""
from __future__ import annotations

import csv as _csv
import json as _json
from pathlib import Path

from corpus2node.core.text import normalize_text
from corpus2node.core.types import SourceFile, SourceKind

_IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp"}
_AUDIO_EXTS = {".mp3", ".wav", ".m4a", ".flac", ".aac", ".ogg"}


def extract_blocks_for(source: SourceFile) -> list[str]:
    """Extract text blocks from a source file by its extension."""
    ext = Path(source.filename).suffix.lower()
    adapter = _ADAPTERS.get(ext)
    if adapter is None:
        raise RuntimeError(
            f"Unsupported file type {ext!r}. Supported: {', '.join(sorted(_ADAPTERS))}."
        )
    blocks = [block for block in adapter(source.filename, source.storage_path) if normalize_text(block)]
    if not blocks:
        raise RuntimeError(f"No extractable text found in {source.filename}.")
    return blocks


def kind_for(filename: str) -> SourceKind:
    ext = Path(filename).suffix.lower()
    if ext == ".pdf":
        return SourceKind.pdf
    if ext in _AUDIO_EXTS:
        return SourceKind.audio
    if ext in _IMAGE_EXTS:
        return SourceKind.image
    return SourceKind.document


# ── adapters ────────────────────────────────────────────────────────────────

def _read_text(filename: str, path: str) -> list[str]:
    return [Path(path).read_text(encoding="utf-8", errors="replace")]


def _read_docx(filename: str, path: str) -> list[str]:
    try:
        import docx
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError("DOCX ingestion needs `python-docx`.") from exc
    document = docx.Document(path)
    parts = [p.text for p in document.paragraphs if p.text.strip()]
    for table in document.tables:
        for row in table.rows:
            cells = [cell.text.strip() for cell in row.cells if cell.text.strip()]
            if cells:
                parts.append(" | ".join(cells))
    return ["\n\n".join(parts)]


def _read_pptx(filename: str, path: str) -> list[str]:
    try:
        from pptx import Presentation
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError("PPTX ingestion needs `python-pptx`.") from exc
    presentation = Presentation(path)
    blocks: list[str] = []
    for slide in presentation.slides:  # one block per slide (slide = natural unit)
        texts = [
            shape.text_frame.text.strip()
            for shape in slide.shapes
            if shape.has_text_frame and shape.text_frame.text.strip()
        ]
        if texts:
            blocks.append("\n".join(texts))
    return blocks


def _read_csv(filename: str, path: str) -> list[str]:
    rows: list[str] = []
    with open(path, newline="", encoding="utf-8", errors="replace") as handle:
        for row in _csv.reader(handle):
            cells = [cell.strip() for cell in row if cell.strip()]
            if cells:
                rows.append(" | ".join(cells))
    return ["\n".join(rows)]


def _read_json(filename: str, path: str) -> list[str]:
    data = _json.loads(Path(path).read_text(encoding="utf-8", errors="replace"))
    return [_json.dumps(data, ensure_ascii=False, indent=2)]


def _read_yaml(filename: str, path: str) -> list[str]:
    try:
        import yaml
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError("YAML ingestion needs `pyyaml`.") from exc
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8", errors="replace"))
    return [_json.dumps(data, ensure_ascii=False, indent=2) if data is not None else ""]


def _read_pdf(filename: str, path: str) -> list[str]:
    from corpus2node.ingest.pdf_kimi import extract_pdf_blocks

    return extract_pdf_blocks(filename, path)


def _read_image(filename: str, path: str) -> list[str]:
    from corpus2node.ingest.image_kimi import describe_image

    return describe_image(filename, path)


def _read_audio(filename: str, path: str) -> list[str]:
    from corpus2node.ingest.audio_whisper import transcribe_audio

    return transcribe_audio(filename, path)


_ADAPTERS = {
    ".pdf": _read_pdf,
    ".txt": _read_text,
    ".md": _read_text,
    ".markdown": _read_text,
    ".docx": _read_docx,
    ".pptx": _read_pptx,
    ".csv": _read_csv,
    ".json": _read_json,
    ".yaml": _read_yaml,
    ".yml": _read_yaml,
    **{ext: _read_image for ext in _IMAGE_EXTS},
    **{ext: _read_audio for ext in _AUDIO_EXTS},
}

SUPPORTED_EXTENSIONS = frozenset(_ADAPTERS)
