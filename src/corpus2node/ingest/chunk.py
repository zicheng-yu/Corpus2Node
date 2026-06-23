"""Chunk extracted source text into EvidenceChunks (structure-aware, locator-preserving).

PDF (Kimi) and audio (Whisper) adapters that produce the raw text/blocks are ported
separately; this module is the shared chunking step they feed into.
"""
from __future__ import annotations

from corpus2node.core.types import EvidenceChunk, SourceKind
from corpus2node.core.text import chunk_text, summarize_text


def make_chunks(
    source_id: str,
    source_type: SourceKind,
    text: str,
    *,
    page_start: int | None = None,
    max_chars: int = 900,
) -> list[EvidenceChunk]:
    """Chunk a single block of source text. ``page_start`` is carried onto every
    chunk as a citation locator when known (e.g. one block == one PDF page)."""
    chunks: list[EvidenceChunk] = []
    for index, piece in enumerate(chunk_text(text, max_chars=max_chars), start=1):
        chunks.append(
            EvidenceChunk(
                chunk_id=f"{source_id}-c{index}",
                source_id=str(source_id),
                source_type=source_type,
                text=piece,
                summary=summarize_text(piece, max_sentences=1, max_chars=160),
                keywords=[],
                embedding=[],
                page_start=page_start,
                page_end=page_start,
            )
        )
    return chunks


def make_chunks_from_blocks(
    source_id: str,
    source_type: SourceKind,
    blocks: list[str],
    *,
    page_offset: int = 1,
    max_chars: int = 900,
) -> list[EvidenceChunk]:
    """Chunk a sequence of text blocks. Only record a page locator when the source
    is genuinely multi-block (e.g. a paginated PDF); a single block (md/docx/txt or
    a PDF that came back as one blob) must NOT label every chunk as "第1页"."""
    paginated = len(blocks) > 1
    chunks: list[EvidenceChunk] = []
    for block_index, block in enumerate(blocks, start=page_offset):
        for piece in chunk_text(block, max_chars=max_chars):
            number = len(chunks) + 1
            chunks.append(
                EvidenceChunk(
                    chunk_id=f"{source_id}-d{block_index}-{number}",
                    source_id=str(source_id),
                    source_type=source_type,
                    text=piece,
                    summary=summarize_text(piece, max_sentences=1, max_chars=160),
                    keywords=[],
                    embedding=[],
                    page_start=block_index if paginated else None,
                    page_end=block_index if paginated else None,
                )
            )
    return chunks
