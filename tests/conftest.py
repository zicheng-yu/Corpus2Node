from __future__ import annotations

import pytest

from corpus2node.config import settings
from corpus2node.llm import store


@pytest.fixture(autouse=True)
def isolate_storage(tmp_path, monkeypatch):
    """Each test gets a fresh storage dir and a clean LLM-registry cache, with
    ambient provider keys cleared so env never leaks into assertions."""
    monkeypatch.setattr(settings, "local_storage_path", str(tmp_path))
    for var in ("OPENAI_API_KEY", "ANTHROPIC_API_KEY", "KIMI_API_KEY", "EMBEDDING_API_KEY", "EMBED_PROVIDER"):
        monkeypatch.delenv(var, raising=False)
    store.reset_cache()
    yield
    store.reset_cache()
