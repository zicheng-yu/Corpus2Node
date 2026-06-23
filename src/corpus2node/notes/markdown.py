"""Deterministic markdown post-processing for generated notes.

Ported (near-verbatim) from the donor's notes.py — this is the tuned, defensive
half of the old 902-line file: it repairs LLM markdown that arrives with escaped or
collapsed newlines, strips duplicate headings the model echoes back, and numbers
sections. Pure functions, no LLM, no IO; the generator orchestrates them.
"""
from __future__ import annotations

import re

from corpus2node.core.text import normalize_text
from corpus2node.core.types import NoteSection, NoteReference

__all__ = [
    "clean_section_markdown",
    "coerce_note_sections",
    "number_sections",
    "heading_key",
    "strip_section_number",
]


def heading_key(text: str) -> str:
    return re.sub(r"[^\w一-鿿]+", "", normalize_text(text)).lower()


def strip_section_number(title: str) -> str:
    return re.sub(r"^第\s*\d+\s*[章节讲课][：:、.\s-]*", "", title).strip()


def clean_section_markdown(title: str, content_md: str) -> str:
    """Repair collapsed/escaped markdown and drop a heading that echoes the title."""
    markdown = _normalize_note_markdown(content_md)
    return _remove_duplicate_section_heading(title, markdown)


def coerce_note_sections(
    sections: list,
    *,
    valid_concept_ids: set[str],
    references_by_index: dict[int, list[NoteReference]] | None = None,
) -> list[NoteSection]:
    """Validate LLM sections into NoteSection (drop empties, clean md, keep valid concept_ids).

    ``references_by_index`` (optional) attaches the chunks each section was grounded
    in; they are stored on the section (excluded from the wire) for traceability/eval.
    """
    references_by_index = references_by_index or {}
    out: list[NoteSection] = []
    for index, section in enumerate(sections):
        title = getattr(section, "title", "")
        content_md = getattr(section, "content_md", "")
        if not normalize_text(title) and not _normalize_note_markdown(content_md):
            continue
        concept_ids: list[str] = []
        seen: set[str] = set()
        for concept_id in getattr(section, "concept_ids", []) or []:
            if concept_id not in valid_concept_ids or concept_id in seen:
                continue
            concept_ids.append(concept_id)
            seen.add(concept_id)
        out.append(
            NoteSection(
                title=normalize_text(title) or "学习笔记",
                content_md=clean_section_markdown(title, content_md) or "- 暂无内容。",
                concept_ids=concept_ids,
                references=references_by_index.get(index, []),
            )
        )
    return out


def number_sections(sections: list[NoteSection]) -> list[NoteSection]:
    numbered: list[NoteSection] = []
    seen_titles: set[str] = set()
    for index, section in enumerate(sections, start=1):
        title = strip_section_number(normalize_text(section.title)) or "核心主题"
        if heading_key(title) in seen_titles:
            title = f"{title}（{index}）"
        seen_titles.add(heading_key(title))
        numbered.append(section.model_copy(update={"title": f"第 {index} 节：{title}"}))
    return numbered


# ── internal: markdown repair ─────────────────────────────────────────────────


def _normalize_note_markdown(text: str) -> str:
    markdown = text.replace("\\n", "\n").replace("\\r", "\n").replace("\\t", "  ")
    markdown = markdown.replace("\r\n", "\n").replace("\r", "\n")
    markdown = re.sub(r"[ \t]+\n", "\n", markdown)
    markdown = re.sub(r"\n{3,}", "\n\n", markdown)
    if _markdown_looks_collapsed(markdown):
        markdown = _restore_markdown_breaks(markdown)
    return markdown.strip()


def _remove_duplicate_section_heading(title: str, markdown: str) -> str:
    normalized_title = heading_key(title)
    if not normalized_title:
        return markdown
    lines = markdown.splitlines()
    if not lines:
        return markdown
    match = re.match(r"^#{1,6}\s+(.+?)\s*$", lines[0])
    if not match or heading_key(match.group(1)) != normalized_title:
        return markdown
    remaining = lines[1:]
    while remaining and not remaining[0].strip():
        remaining.pop(0)
    return "\n".join(remaining).strip()


def _markdown_looks_collapsed(markdown: str) -> bool:
    stripped = markdown.strip()
    if not stripped:
        return False
    if "\n" not in stripped:
        return bool(re.search(r"(#{2,6}\s+| - |\s```)", stripped))
    return any(
        len(line) > 220 and re.search(r"(#{2,6}\s+| - |\s```)", line)
        for line in stripped.splitlines()
    )


def _restore_markdown_breaks(markdown: str) -> str:
    text = re.sub(r"\s+", " ", markdown.strip())

    def code_block_replacer(match: re.Match[str]) -> str:
        language = match.group(1).strip()
        body = match.group(2).strip()
        return f"\n\n```{language}\n{body}\n```\n\n"

    text = re.sub(r"```([A-Za-z0-9_-]*)\s+(.*?)\s+```", code_block_replacer, text)
    text = re.sub(r"\s+(#{2,6}\s+)", r"\n\n\1", text)
    text = re.sub(r"\s+-\s+(\*\*|`|[A-Za-z0-9一-鿿])", r"\n- \1", text)
    text = re.sub(r"\s+(\d+\.\s+)", r"\n\1", text)

    lines = [_split_collapsed_heading(line.strip()) for line in text.splitlines()]
    restored = "\n".join(line for line in lines if line)
    restored = re.sub(r"(?m)^(#{2,6}\s+.+)\n(?!\n)", r"\1\n\n", restored)
    restored = re.sub(r"(?m)([^\n])\n(#{2,6}\s+)", r"\1\n\n\2", restored)
    restored = re.sub(r"(?m)([^\n])\n(-\s+)", r"\1\n\n\2", restored)
    restored = re.sub(r"\n{3,}", "\n\n", restored)
    return restored.strip()


def _split_collapsed_heading(line: str) -> str:
    match = re.match(r"^(#{2,6}\s+)(.+)$", line)
    if not match:
        return line
    prefix, content = match.groups()

    title, separator, rest = content.partition(" ")
    if separator and 2 <= len(title) <= 28 and _contains_cjk(title):
        return f"{prefix}{title}\n\n{rest.strip()}"

    for marker in (" ```", " - ", " 1. "):
        index = content.find(marker)
        if 2 <= index <= 40:
            return f"{prefix}{content[:index].strip()}\n\n{content[index:].strip()}"
    return line


def _contains_cjk(text: str) -> bool:
    return bool(re.search(r"[一-鿿]", text))
