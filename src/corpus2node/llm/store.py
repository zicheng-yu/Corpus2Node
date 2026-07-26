from __future__ import annotations

import os
import re
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from pathlib import Path

from corpus2node.config import settings
from corpus2node.core.clock import utcnow
from corpus2node.llm.credentials import (
    LLMSettings,
    ProviderCredential,
    ProviderKind,
    Purpose,
    PurposeBinding,
)
from corpus2node.storage import local

_LOCK = threading.RLock()
_GLOBAL_SCOPE = "__global__"
_ACTIVE_USER_ID: ContextVar[str | None] = ContextVar("corpus2node_llm_user_id", default=None)
_CACHE: dict[str, LLMSettings] = {}


def _safe_user_id(user_id: str) -> str:
    value = user_id.strip()
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", value):
        raise ValueError("Invalid user id for model-settings storage.")
    return value


def path_for_user(user_id: str | None) -> Path:
    root = Path(settings.local_storage_path)
    if user_id is None:
        return root / "llm_settings.json"
    return root / "users" / _safe_user_id(user_id) / "llm_settings.json"


def active_user_id() -> str | None:
    return _ACTIVE_USER_ID.get()


@contextmanager
def user_scope(user_id: str) -> Iterator[None]:
    """Bind model resolution to one authenticated user for this async context."""
    token = _ACTIVE_USER_ID.set(_safe_user_id(user_id))
    try:
        yield
    finally:
        _ACTIVE_USER_ID.reset(token)


def _scope() -> tuple[str, str | None]:
    user_id = active_user_id()
    if settings.auth_mode == "accounts" and user_id is None:
        raise RuntimeError("Authenticated model settings require an active user scope.")
    return (user_id or _GLOBAL_SCOPE), user_id


def load() -> LLMSettings:
    """Load the current user's registry, or the legacy local registry outside account mode."""
    scope, user_id = _scope()
    with _LOCK:
        value = _CACHE.get(scope)
        if value is None:
            path = path_for_user(user_id)
            if path.exists():
                value = LLMSettings.model_validate_json(path.read_text(encoding="utf-8"))
            else:
                # Hosted accounts start empty: ambient server keys must never become
                # every user's credential. Legacy/local mode keeps env bootstrapping.
                value = LLMSettings() if user_id is not None else _bootstrap_from_env()
                _write(value, user_id)
            # One-time migration: Kimi used to live in .env; if an old registry already
            # has a Kimi-looking credential but no `vision` binding, bind it so image/
            # PDF/video ingest keeps working without manual re-config.
            if _ensure_vision_binding(value):
                _write(value, user_id)
            _CACHE[scope] = value
        return value


def save(value: LLMSettings) -> LLMSettings:
    _, user_id = _scope()
    with _LOCK:
        value.updated_at = utcnow()
        _write(value, user_id)
        return value


def reset_cache() -> None:
    """Drop every in-memory registry (used by tests and after external edits)."""
    with _LOCK:
        _CACHE.clear()


def _write(value: LLMSettings, user_id: str | None) -> None:
    scope = user_id or _GLOBAL_SCOPE
    path = path_for_user(user_id)
    local.write_text_atomic(path, value.model_dump_json(indent=2))
    path.chmod(0o600)
    _CACHE[scope] = value


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
