"""Local PDF text extraction via pypdf — the fully-offline path.

Reads the embedded text layer page by page; one block per page so downstream
chunking keeps page locators (mirrors pdf_kimi's page-ish blocks). Scanned /
image-only PDFs have no text layer — OCR needs the Kimi (Moonshot) vision
credential, and the error message says exactly that.
"""
from __future__ import annotations

from pathlib import Path

from corpus2node.core.text import normalize_text


def extract_pdf_blocks_local(filename: str, pdf_path: str | Path) -> list[str]:
    """Extract a PDF into per-page text blocks with pypdf (no network, no key)."""
    try:
        from pypdf import PdfReader
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError("本地 PDF 解析需要 `pypdf` 包，请运行 `uv sync`。") from exc

    reader = PdfReader(str(pdf_path))
    blocks: list[str] = []
    for page in reader.pages:
        try:
            text = normalize_text(page.extract_text() or "")
        except Exception:  # a corrupt page shouldn't sink the whole document
            text = ""
        if text:
            blocks.append(text)
    if not blocks:
        raise RuntimeError(
            f"{filename} 没有可提取的文本层（可能是扫描件）。"
            "扫描 PDF 的 OCR 需要在「设置 → 模型」把 vision 用途绑定到 Kimi（Moonshot）凭据。"
        )
    return blocks
