from __future__ import annotations

from fastapi import APIRouter

from corpus2node import prompt_store
from corpus2node.prompt_store import PromptSettings

router = APIRouter(prefix="/settings/prompts", tags=["settings"])


@router.get("")
def get_prompts() -> PromptSettings:
    return prompt_store.load()


@router.put("")
def set_prompts(payload: PromptSettings) -> PromptSettings:
    return prompt_store.save(payload)
