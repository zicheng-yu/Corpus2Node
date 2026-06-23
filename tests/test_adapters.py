from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

from corpus2node.config import settings
from corpus2node.core.types import SourceFile, SourceKind
from corpus2node.ingest import adapters


def _src(filename: str, path: Path) -> SourceFile:
    return SourceFile(
        kind=SourceKind.document, filename=filename, content_type="x",
        storage_path=str(path), size_bytes=path.stat().st_size,
    )


def test_markdown_adapter(tmp_path):
    p = tmp_path / "a.md"
    p.write_text("# 标题\n\n二叉搜索树 用于 高效 查找。", encoding="utf-8")
    blocks = adapters.extract_blocks_for(_src("a.md", p))
    assert blocks and "二叉搜索树" in blocks[0]


def test_docx_adapter(tmp_path):
    import docx

    document = docx.Document()
    document.add_paragraph("二叉搜索树是一种树结构。")
    document.add_paragraph("用于高效查找。")
    p = tmp_path / "a.docx"
    document.save(str(p))
    blocks = adapters.extract_blocks_for(_src("a.docx", p))
    assert blocks and "二叉搜索树" in blocks[0]


def test_pptx_adapter(tmp_path):
    from pptx import Presentation
    from pptx.util import Inches

    presentation = Presentation()
    slide = presentation.slides.add_slide(presentation.slide_layouts[6])  # blank
    box = slide.shapes.add_textbox(Inches(1), Inches(1), Inches(6), Inches(2))
    box.text_frame.text = "树结构 用于 组织 层次 数据"
    p = tmp_path / "a.pptx"
    presentation.save(str(p))
    blocks = adapters.extract_blocks_for(_src("a.pptx", p))
    assert blocks and any("树结构" in block for block in blocks)


def test_csv_adapter(tmp_path):
    p = tmp_path / "a.csv"
    p.write_text("名称,定义\n二叉搜索树,用于查找的树\n", encoding="utf-8")
    blocks = adapters.extract_blocks_for(_src("a.csv", p))
    assert blocks and "二叉搜索树" in blocks[0]


def test_json_adapter(tmp_path):
    p = tmp_path / "a.json"
    p.write_text(json.dumps({"concept": "二叉搜索树"}, ensure_ascii=False), encoding="utf-8")
    blocks = adapters.extract_blocks_for(_src("a.json", p))
    assert blocks and "二叉搜索树" in blocks[0]


def test_unsupported_extension_raises(tmp_path):
    p = tmp_path / "a.exe"
    p.write_bytes(b"\x00\x01")
    with pytest.raises(RuntimeError):
        adapters.extract_blocks_for(_src("a.exe", p))


def test_kind_for_maps_extensions():
    assert adapters.kind_for("a.pdf") == SourceKind.pdf
    assert adapters.kind_for("a.md") == SourceKind.document
    assert adapters.kind_for("a.docx") == SourceKind.document
    assert adapters.kind_for("a.png") == SourceKind.image
    assert adapters.kind_for("a.mp3") == SourceKind.audio


def test_image_and_audio_are_registered():
    assert ".png" in adapters.SUPPORTED_EXTENSIONS
    assert ".mp3" in adapters.SUPPORTED_EXTENSIONS


def test_image_adapter_requires_kimi_config(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "kimi_api_key", "")  # force unconfigured -> no network
    p = tmp_path / "a.png"
    p.write_bytes(b"\x89PNG\r\n")
    with pytest.raises(RuntimeError):
        adapters.extract_blocks_for(_src("a.png", p))


def test_audio_adapter_clear_error_without_faster_whisper(tmp_path):
    if importlib.util.find_spec("faster_whisper") is not None:
        pytest.skip("faster-whisper installed; the not-installed path can't be exercised")
    p = tmp_path / "a.mp3"
    p.write_bytes(b"\x00\x01")
    with pytest.raises(RuntimeError):
        adapters.extract_blocks_for(_src("a.mp3", p))
