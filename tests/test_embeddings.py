from __future__ import annotations

import math
import uuid

import pytest

from corpus2node.config import settings
from corpus2node.core.text import cosine_similarity
from corpus2node.core.types import GraphArtifact
from corpus2node.index.embeddings import (
    EmbeddingProvenanceError,
    HashingEmbeddings,
    embedding_signature,
    ensure_embedding_compatible,
    get_embeddings,
)
from corpus2node.llm import store
from corpus2node.llm.credentials import (
    LLMSettings,
    ProviderCredential,
    ProviderKind,
    Purpose,
    PurposeBinding,
)


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


def test_embedding_signature_includes_compat_endpoint_and_is_enforced():
    left = HashingEmbeddings(dims=64)
    right = HashingEmbeddings(dims=64)
    left.openai_api_base = "https://embedding-a.example/v1"
    right.openai_api_base = "https://embedding-b.example/v1"
    graph = GraphArtifact(session_id=uuid.uuid4())
    graph.provenance.embedding_signature = embedding_signature(left)

    ensure_embedding_compatible(graph, left)
    with pytest.raises(EmbeddingProvenanceError):
        ensure_embedding_compatible(graph, right)

    graph.provenance.embedding_signature = ""
    with pytest.raises(EmbeddingProvenanceError):
        ensure_embedding_compatible(graph, left)


def _bind_embedding(kind: ProviderKind, *, base_url: str = "", model: str = "bge-m3") -> None:
    cred = ProviderCredential(
        credential_id="e1", label="emb", kind=kind, base_url=base_url, default_model=model,
        api_key="k-1234" if kind not in (ProviderKind.ollama, ProviderKind.lmstudio) else "",
    )
    store.save(LLMSettings(credentials=[cred], bindings={Purpose.embedding: PurposeBinding(credential_id="e1")}))


def test_get_embeddings_routes_ollama_to_native_client(monkeypatch):
    monkeypatch.setattr(settings, "embed_provider", "openai_compatible")
    _bind_embedding(ProviderKind.ollama)
    embedder = get_embeddings()
    assert type(embedder).__name__ == "OllamaEmbeddings"
    assert embedder.base_url == "http://127.0.0.1:11434"  # native root, not the /v1 compat path
    assert embedder.model == "bge-m3"


def test_get_embeddings_disables_tokenized_input_for_compat_endpoints(monkeypatch):
    # The OpenAIEmbeddings default pre-tokenizes with tiktoken and sends token arrays;
    # only api.openai.com understands those — LM Studio/Ollama/DeepSeek reject them.
    monkeypatch.setattr(settings, "embed_provider", "openai_compatible")
    _bind_embedding(ProviderKind.lmstudio, model="text-embedding-bge-m3")
    embedder = get_embeddings()
    assert type(embedder).__name__ == "OpenAIEmbeddings"
    assert embedder.openai_api_base == "http://127.0.0.1:1234/v1"
    assert embedder.check_embedding_ctx_length is False
