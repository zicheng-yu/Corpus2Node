"""Embedding providers behind the LangChain ``Embeddings`` interface.

- ``HashingEmbeddings``: deterministic, dependency-free — default for tests/offline dev.
- ``BgeM3Embeddings``: local BAAI/bge-m3 via FlagEmbedding (lazy; needs ``--extra ml``).
- OpenAI-compatible: delegated to ``langchain_openai.OpenAIEmbeddings`` with base_url.
"""
from __future__ import annotations

import hashlib
import math
import re

from langchain_core.embeddings import Embeddings

from corpus2node.config import settings

_TOKEN_RE = re.compile(r"[A-Za-z][A-Za-z0-9_+\-]*|[一-鿿]+")


class HashingEmbeddings(Embeddings):
    """Deterministic hashing embedding (signed token hashing into a fixed vector)."""

    def __init__(self, dims: int | None = None) -> None:
        self.dims = dims or settings.embedding_dimensions

    def _embed(self, text: str) -> list[float]:
        vector = [0.0] * self.dims
        for token in _TOKEN_RE.findall(text.lower()):
            digest = hashlib.sha256(token.encode("utf-8")).digest()
            index = int.from_bytes(digest[:4], "big") % self.dims
            sign = 1.0 if digest[4] % 2 == 0 else -1.0
            vector[index] += sign * max(len(token), 1)
        norm = math.sqrt(sum(value * value for value in vector))
        return [value / norm for value in vector] if norm else vector

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [self._embed(text) for text in texts]

    def embed_query(self, text: str) -> list[float]:
        return self._embed(text)


class BgeM3Embeddings(Embeddings):
    """Local BAAI/bge-m3 dense embeddings via FlagEmbedding (lazy-loaded, cached)."""

    _cache: dict[tuple[str, bool], object] = {}

    def __init__(self, model_name: str | None = None, *, use_fp16: bool | None = None) -> None:
        self.model_name = model_name or settings.embedding_local_model_name
        self.use_fp16 = settings.embedding_local_use_fp16 if use_fp16 is None else use_fp16

    def _model(self):
        key = (self.model_name, self.use_fp16)
        if key not in self._cache:
            try:
                from FlagEmbedding import BGEM3FlagModel
            except ImportError as exc:
                raise RuntimeError(
                    "BGE-M3 embeddings require the `ml` extra: run `uv sync --extra ml`."
                ) from exc
            self._cache[key] = BGEM3FlagModel(self.model_name, use_fp16=self.use_fp16)
        return self._cache[key]

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        output = self._model().encode(
            texts, batch_size=max(1, settings.embedding_batch_size), max_length=8192
        )["dense_vecs"]
        return [vector.tolist() if hasattr(vector, "tolist") else list(vector) for vector in output]

    def embed_query(self, text: str) -> list[float]:
        return self.embed_documents([text])[0]


def get_embeddings() -> Embeddings:
    """Build the configured embeddings provider (settings.embed_provider)."""
    provider = settings.embed_provider
    if provider == "bge_m3":
        return BgeM3Embeddings()
    if provider == "openai_compatible":
        from langchain_openai import OpenAIEmbeddings

        from corpus2node.llm import factory
        from corpus2node.llm.credentials import Purpose
        from corpus2node.llm.factory import LLMConfigError

        try:
            params = factory.credential_params(Purpose.embedding)
        except LLMConfigError as exc:
            raise RuntimeError(
                "embed_provider=openai_compatible 需要在「设置 → 模型」里把一个凭据绑定到 embedding 用途"
                "（base_url、api_key、嵌入模型名）。"
            ) from exc
        return OpenAIEmbeddings(
            model=params.model,
            base_url=params.base_url or None,
            api_key=params.api_key or None,
        )
    if provider == "hashing":
        return HashingEmbeddings()
    raise RuntimeError(f"Unknown embed_provider: {provider!r}")
