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

from pathlib import Path

from pydantic import BaseModel

from corpus2node.config import settings

AREAS = ("chat", "notes", "exam")


class PromptSettings(BaseModel):
    global_instructions: str = ""
    chat: str = ""
    notes: str = ""
    exam: str = ""


def _path() -> Path:
    return Path(settings.local_storage_path) / "prompt_settings.json"


def load() -> PromptSettings:
    try:
        return PromptSettings.model_validate_json(_path().read_text(encoding="utf-8"))
    except (FileNotFoundError, ValueError):
        return PromptSettings()


def save(value: PromptSettings) -> PromptSettings:
    path = _path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(value.model_dump_json(indent=2), encoding="utf-8")
    return value


def custom_block(area: str) -> str:
    """The appended-instruction block for an area (global + area-specific), or '' if none."""
    value = load()
    parts = [value.global_instructions, getattr(value, area, "")]
    text = "\n".join(part.strip() for part in parts if part and part.strip())
    if not text:
        return ""
    return (
        "\n\n[用户自定义补充要求]\n"
        f"{text}\n"
        "（在不违反上述规则与输出格式的前提下，尽量遵循这些偏好。）"
    )
