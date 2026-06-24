from __future__ import annotations

from fastapi.testclient import TestClient

from corpus2node import prompt_store
from corpus2node.api.app import app
from corpus2node.prompt_store import PromptSettings

client = TestClient(app)


def test_custom_block_empty_by_default():
    assert prompt_store.load() == PromptSettings()
    assert prompt_store.custom_block("chat") == ""


def test_custom_block_combines_global_and_area():
    prompt_store.save(PromptSettings(global_instructions="统一用简体中文", chat="先给结论再展开"))
    block = prompt_store.custom_block("chat")
    assert "用户自定义补充要求" in block
    assert "统一用简体中文" in block and "先给结论再展开" in block
    # an area without its own text still inherits the global instructions
    notes_block = prompt_store.custom_block("notes")
    assert "统一用简体中文" in notes_block and "先给结论再展开" not in notes_block


def test_save_round_trips():
    prompt_store.save(PromptSettings(exam="偏应用与理解题"))
    assert prompt_store.load().exam == "偏应用与理解题"


def test_prompts_route_get_then_put():
    assert client.get("/settings/prompts").json()["chat"] == ""
    updated = client.put(
        "/settings/prompts",
        json={"global_instructions": "G", "chat": "C", "notes": "", "exam": ""},
    )
    assert updated.status_code == 200 and updated.json()["chat"] == "C"
    assert client.get("/settings/prompts").json()["global_instructions"] == "G"
