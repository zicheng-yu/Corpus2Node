"""Text utilities: normalization, sentence/structure-aware chunking, term cleaning.

Ported from the donor's tuned helpers; the chunker is rewritten to be
paragraph-aware with sentence-level overlap (donor packed to a flat 500 chars).
"""
from __future__ import annotations

import re

_PUNCT_RE = re.compile(r"[^\w一-鿿]+", re.UNICODE)
_SENTENCE_RE = re.compile(r"(?<=[。！？!?;；\.])\s+")

EN_STOPWORDS = {
    "the", "and", "for", "that", "with", "this", "from", "into", "your", "have",
    "will", "then", "than", "when", "what", "where", "which", "while", "about",
    "their", "there", "them", "they", "been", "being", "also", "such", "using",
    "used", "between", "through", "because", "each", "some", "more", "most",
    "other", "many", "much", "very", "just", "only", "over", "under",
}

ZH_STOPWORDS = {
    "我们", "你们", "他们", "这个", "那个", "一种", "以及", "如果", "因为", "所以", "然后",
    "就是", "可以", "需要", "进行", "通过", "一个", "一些", "没有", "不是", "这种",
    "什么", "怎么", "这里", "那里", "已经", "对于", "关于", "而且", "并且", "或者", "还是",
    "只有", "只要", "虽然", "但是", "不仅", "作为", "为了", "这些", "那些", "自己",
}


def normalize_text(text: str) -> str:
    text = text.replace("\\n", " ").replace("\\t", " ").replace("\\r", " ")
    return re.sub(r"\s+", " ", text).strip()


def split_sentences(text: str) -> list[str]:
    normalized = normalize_text(text)
    if not normalized:
        return []
    parts = [part.strip() for part in _SENTENCE_RE.split(normalized) if part.strip()]
    return parts or [normalized]


def summarize_text(text: str, max_sentences: int = 2, max_chars: int = 220) -> str:
    sentences = split_sentences(text)
    if not sentences:
        return ""
    return " ".join(sentences[:max_sentences])[:max_chars].strip()


def chunk_text(text: str, *, max_chars: int = 900, overlap_sentences: int = 2) -> list[str]:
    """Paragraph-aware, sentence-packed windows with sentence-level overlap.

    Respects blank-line paragraph boundaries, packs sentences up to ``max_chars``,
    carries the last ``overlap_sentences`` into the next window, and hard-splits
    any single sentence longer than ``max_chars``.
    """
    blocks = [block.strip() for block in re.split(r"\n\s*\n", text) if block.strip()]
    sentences: list[str] = []
    for block in blocks:
        sentences.extend(split_sentences(block))
    if not sentences:
        return []

    chunks: list[str] = []
    current: list[str] = []
    current_len = 0
    for sentence in sentences:
        if len(sentence) > max_chars:
            if current:
                chunks.append(" ".join(current))
                current, current_len = [], 0
            for start in range(0, len(sentence), max_chars):
                chunks.append(sentence[start:start + max_chars].strip())
            continue
        if current and current_len + len(sentence) + 1 > max_chars:
            chunks.append(" ".join(current))
            current = current[-overlap_sentences:] if overlap_sentences else []
            current_len = sum(len(item) + 1 for item in current)
        current.append(sentence)
        current_len += len(sentence) + 1
    if current:
        chunks.append(" ".join(current))
    return [chunk.strip() for chunk in chunks if chunk.strip()]


def canonicalize_term(term: str) -> str:
    cleaned = _PUNCT_RE.sub(" ", term).strip().lower()
    return re.sub(r"\s+", " ", cleaned)


def is_reasonable_term(term: str) -> bool:
    if term.isdigit() or len(term) <= 1:
        return False
    if all(char == term[0] for char in term):
        return False
    return term not in EN_STOPWORDS and term not in ZH_STOPWORDS


def cosine_similarity(left: list[float], right: list[float]) -> float:
    if not left or not right or len(left) != len(right):
        return 0.0
    return sum(a * b for a, b in zip(left, right))
