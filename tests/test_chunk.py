from __future__ import annotations

from corpus2node.core.types import SourceKind
from corpus2node.ingest.chunk import make_chunks, make_chunks_from_blocks
from corpus2node.core.text import chunk_text


def test_chunk_text_windows_and_caps():
    text = "。".join(f"这是第{i}句话用于测试分块逻辑是否正确" for i in range(40)) + "。"
    pieces = chunk_text(text, max_chars=120, overlap_sentences=1)
    assert len(pieces) > 1
    assert all(len(piece) <= 240 for piece in pieces)  # generous slack over max_chars


def test_make_chunks_plain_text():
    chunks = make_chunks("src", SourceKind.pdf, "线性表是一种数据结构。" * 30, max_chars=120)
    assert chunks
    assert all(chunk.source_id == "src" for chunk in chunks)
    assert all(chunk.chunk_id.startswith("src-c") for chunk in chunks)


def test_make_chunks_from_blocks_preserves_page_locator():
    blocks = ["第一页内容用于测试。" * 20, "第二页内容用于测试。" * 20]
    chunks = make_chunks_from_blocks("src", SourceKind.pdf, blocks, max_chars=100)
    assert chunks
    assert chunks[0].page_start == 1
    assert any(chunk.page_start == 2 for chunk in chunks)
