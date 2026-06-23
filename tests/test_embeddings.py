from __future__ import annotations

import math

from corpus2node.core.text import cosine_similarity
from corpus2node.index.embeddings import HashingEmbeddings


def test_hashing_is_deterministic_and_normalized():
    embedder = HashingEmbeddings(dims=64)
    first = embedder.embed_query("二叉搜索树 binary search tree")
    second = embedder.embed_query("二叉搜索树 binary search tree")
    assert first == second
    assert len(first) == 64
    assert abs(math.sqrt(sum(value * value for value in first)) - 1.0) < 1e-6


def test_hashing_reflects_token_overlap():
    embedder = HashingEmbeddings(dims=256)
    a = embedder.embed_query("二叉搜索树 | 一种树结构 | 用于查找")
    b = embedder.embed_query("二叉搜索树 | 一种树结构 | 用于查找 | bst")
    c = embedder.embed_query("傅里叶变换 | 频域分析 | 信号处理")
    assert cosine_similarity(a, b) > 0.8  # near-duplicate
    assert cosine_similarity(a, c) < 0.5  # unrelated
