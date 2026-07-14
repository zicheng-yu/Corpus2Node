"""User-customizable prompt instructions, appended to the built-in system prompts.

Design (per the chosen approach): the built-in system prompts are *kept* — they
guarantee structured output / grounding behavior — and the user's text is *appended*
as an extra "preferences" block (global + per-area). This keeps customization safe:
a user can steer tone/focus without being able to break the JSON/citation contracts.

Persisted as a small JSON next to the other artifacts; read on demand (no cache, so it
stays correct under the per-test storage isolation). Areas: chat / notes / exam — the
generative, user-facing purposes; graph extraction & critic are left strict on purpose.
"""
from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from pathlib import Path

from pydantic import BaseModel

from corpus2node.config import settings
from corpus2node.storage import local

AREAS = ("chat", "notes", "exam")
_OWNER_KEY: ContextVar[str | None] = ContextVar("prompt_owner_key", default=None)


class PromptSettings(BaseModel):
    global_instructions: str = ""
    chat: str = ""
    notes: str = ""
    exam: str = ""


def _path(owner_key: str | None = None) -> Path:
    if owner_key:
        safe_parts = [part for part in owner_key.split("/") if part and part not in {".", ".."}]
        if not safe_parts:
            raise ValueError("Invalid prompt owner key.")
        return Path(settings.local_storage_path) / "user_state" / Path(*safe_parts) / "prompt_settings.json"
    return Path(settings.local_storage_path) / "prompt_settings.json"


def settings_path(owner_key: str | None = None) -> Path:
    return _path(owner_key)


def load(owner_key: str | None = None) -> PromptSettings:
    try:
        return PromptSettings.model_validate_json(_path(owner_key).read_text(encoding="utf-8"))
    except (FileNotFoundError, ValueError):
        return PromptSettings()


def save(value: PromptSettings, owner_key: str | None = None) -> PromptSettings:
    local.write_text_atomic(_path(owner_key), value.model_dump_json(indent=2))
    return value


@contextmanager
def owner_context(owner_key: str | None):
    token = _OWNER_KEY.set(owner_key)
    try:
        yield
    finally:
        _OWNER_KEY.reset(token)


def custom_block(area: str) -> str:
    """The appended-instruction block for an area (global + area-specific), or '' if none."""
    value = load(_OWNER_KEY.get())
    parts = [value.global_instructions, getattr(value, area, "")]
    text = "\n".join(part.strip() for part in parts if part and part.strip())
    if not text:
        return ""
    return (
        "\n\n[用户自定义补充要求]\n"
        f"{text}\n"
        "（在不违反上述规则与输出格式的前提下，尽量遵循这些偏好。）"
    )
