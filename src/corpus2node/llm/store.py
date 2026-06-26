from __future__ import annotations

import os
import threading
from corpus2node.core.clock import utcnow
from pathlib import Path

from corpus2node.config import settings
from corpus2node.llm.credentials import (
    LLMSettings,
    ProviderCredential,
    ProviderKind,
    Purpose,
    PurposeBinding,
)
from corpus2node.storage import local

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
            # One-time migration: Kimi used to live in .env; if an old registry already
            # has a Kimi-looking credential but no `vision` binding, bind it so image/
            # PDF/video ingest keeps working without manual re-config.
            if _ensure_vision_binding(_CACHE):
                _write(_CACHE)
        return _CACHE


def save(value: LLMSettings) -> LLMSettings:
    with _LOCK:
        value.updated_at = utcnow()
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
    local.write_text_atomic(path, value.model_dump_json(indent=2))
    _CACHE = value


def _bootstrap_from_env() -> LLMSettings:
    """First-run convenience: seed credentials from exported env vars if present.

    Chat purposes (graph/chat/critic/exam) are left UNBOUND — the user picks those, so
    an ambient key never silently becomes the model behind every feature. The
    single-provider purposes (vision = Kimi, embedding) ARE bound when seeded, since
    there is no ambiguity about what they are for.
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
    kimi_key = os.environ.get("KIMI_API_KEY")
    if kimi_key:
        kimi = ProviderCredential(
            label="Kimi (env)",
            kind=ProviderKind.openai,
            base_url=os.environ.get("KIMI_BASE_URL", "https://api.moonshot.cn/v1"),
            api_key=kimi_key,
            default_model=os.environ.get("KIMI_MODEL", "kimi-k2.6"),
        )
        out.credentials.append(kimi)
        out.bindings[Purpose.vision] = PurposeBinding(credential_id=kimi.credential_id)
    if os.environ.get("EMBED_PROVIDER") == "openai_compatible":
        emb_key = os.environ.get("EMBEDDING_API_KEY")
        if emb_key:
            emb = ProviderCredential(
                label="Embedding (env)",
                kind=ProviderKind.openai,
                base_url=os.environ.get("EMBEDDING_BASE_URL", ""),
                api_key=emb_key,
                default_model=os.environ.get("EMBEDDING_MODEL", ""),
            )
            out.credentials.append(emb)
            out.bindings[Purpose.embedding] = PurposeBinding(credential_id=emb.credential_id)
    return out


def _ensure_vision_binding(value: LLMSettings) -> bool:
    """Bind the `vision` purpose to an existing Kimi-looking credential if it is unbound.

    Bridges users whose registry predates Kimi living in the registry. Idempotent:
    returns True (and the caller persists) only when it actually adds the binding.
    """
    if Purpose.vision in value.bindings:
        return False
    kimi = next(
        (
            c
            for c in value.credentials
            if c.kind == ProviderKind.openai
            and ("moonshot" in c.base_url.lower() or "kimi" in c.label.lower() or "kimi" in c.default_model.lower())
        ),
        None,
    )
    if kimi is None:
        return False
    value.bindings[Purpose.vision] = PurposeBinding(credential_id=kimi.credential_id)
    return True
