from __future__ import annotations

import os
import threading
from datetime import datetime
from pathlib import Path

from corpus2node.config import settings
from corpus2node.llm.credentials import LLMSettings, ProviderCredential, ProviderKind

_LOCK = threading.RLock()
_CACHE: LLMSettings | None = None


def _path() -> Path:
    return Path(settings.local_storage_path) / "llm_settings.json"


def load() -> LLMSettings:
    """Load the registry (cached). Bootstraps from env + persists on first run."""
    global _CACHE
    with _LOCK:
        if _CACHE is None:
            path = _path()
            if path.exists():
                _CACHE = LLMSettings.model_validate_json(path.read_text(encoding="utf-8"))
            else:
                _CACHE = _bootstrap_from_env()
                _write(_CACHE)
        return _CACHE


def save(value: LLMSettings) -> LLMSettings:
    with _LOCK:
        value.updated_at = datetime.utcnow()
        _write(value)
        return value


def reset_cache() -> None:
    """Drop the in-memory cache (used by tests and after external edits)."""
    global _CACHE
    with _LOCK:
        _CACHE = None


def _write(value: LLMSettings) -> None:
    global _CACHE
    path = _path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(value.model_dump_json(indent=2), encoding="utf-8")
    _CACHE = value


def _bootstrap_from_env() -> LLMSettings:
    """First-run convenience: seed credentials from common env vars if present.

    No purpose bindings are created — the user binds purposes explicitly (so an
    ambient key never silently becomes the model behind every feature).
    """
    out = LLMSettings()
    openai_key = os.environ.get("OPENAI_API_KEY")
    if openai_key:
        out.credentials.append(
            ProviderCredential(
                label="OpenAI (env)",
                kind=ProviderKind.openai,
                base_url=os.environ.get("OPENAI_BASE_URL", ""),
                api_key=openai_key,
                default_model=os.environ.get("OPENAI_MODEL", ""),
            )
        )
    anthropic_key = os.environ.get("ANTHROPIC_API_KEY")
    if anthropic_key:
        out.credentials.append(
            ProviderCredential(
                label="Anthropic (env)",
                kind=ProviderKind.anthropic,
                base_url=os.environ.get("ANTHROPIC_BASE_URL", ""),
                api_key=anthropic_key,
                default_model=os.environ.get("ANTHROPIC_MODEL", ""),
            )
        )
    return out
