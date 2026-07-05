from __future__ import annotations

from fastapi.testclient import TestClient

from corpus2node.api.app import app

client = TestClient(app)


def test_add_credential_masks_secret_and_bind():
    # starts empty (isolated tmp storage, env cleared)
    body = client.get("/settings/llm").json()
    assert body["credentials"] == []
    assert "graph" in body["purposes"]

    res = client.post(
        "/settings/llm/credentials",
        json={
            "label": "DeepSeek",
            "kind": "openai",
            "base_url": "https://api.deepseek.com",
            "api_key": "sk-secret-abcd",
            "default_model": "deepseek-chat",
        },
    )
    assert res.status_code == 200
    cred = res.json()["credentials"][0]
    cred_id = cred["credential_id"]
    assert cred["has_key"] is True
    assert cred["api_key_preview"].endswith("abcd")
    # the raw secret must never be returned
    assert "sk-secret-abcd" not in res.text

    res = client.put("/settings/llm/bindings/chat", json={"credential_id": cred_id, "model": "deepseek-chat"})
    assert res.status_code == 200
    bindings = {b["purpose"]: b for b in res.json()["bindings"]}
    assert bindings["chat"]["resolved"] is True


def test_bind_to_unknown_credential_is_rejected():
    res = client.put("/settings/llm/bindings/exam", json={"credential_id": "nope", "model": "x"})
    assert res.status_code == 400


def test_delete_credential_drops_its_bindings():
    res = client.post(
        "/settings/llm/credentials",
        json={"label": "A", "kind": "openai", "api_key": "key-1234", "default_model": "m"},
    )
    cred_id = res.json()["credentials"][0]["credential_id"]
    client.put("/settings/llm/bindings/graph", json={"credential_id": cred_id, "model": "m"})

    res = client.delete(f"/settings/llm/credentials/{cred_id}")
    assert res.status_code == 200
    assert res.json()["credentials"] == []
    assert res.json()["bindings"] == []


def test_local_credential_roundtrips_tuning_fields():
    res = client.post(
        "/settings/llm/credentials",
        json={
            "label": "ollama", "kind": "ollama", "default_model": "gemma3:4b",
            "num_ctx": 16384, "max_concurrency": 2,  # no api_key — local servers need none
        },
    )
    assert res.status_code == 200
    cred = res.json()["credentials"][0]
    assert cred["kind"] == "ollama"
    assert cred["has_key"] is False
    assert cred["num_ctx"] == 16384
    assert cred["max_concurrency"] == 2


class _FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


def test_list_models_ollama_uses_native_tags(monkeypatch):
    seen = {}

    def fake_get(url, **kwargs):
        seen["url"] = url
        return _FakeResponse({"models": [{"name": "gemma3:4b"}, {"name": "qwen3:4b"}]})

    monkeypatch.setattr("httpx.get", fake_get)
    res = client.post("/settings/llm/models", json={"kind": "ollama"})
    assert res.status_code == 200
    assert res.json() == {"models": ["gemma3:4b", "qwen3:4b"], "error": None}
    assert seen["url"] == "http://127.0.0.1:11434/api/tags"


def test_list_models_openai_compat_uses_models_route(monkeypatch):
    seen = {}

    def fake_get(url, headers=None, **kwargs):
        seen["url"] = url
        seen["headers"] = headers or {}
        return _FakeResponse({"data": [{"id": "text-embedding-bge-m3"}, {"id": "qwen3-4b"}]})

    monkeypatch.setattr("httpx.get", fake_get)
    res = client.post("/settings/llm/models", json={"kind": "lmstudio"})
    assert res.json()["models"] == ["qwen3-4b", "text-embedding-bge-m3"]
    assert seen["url"] == "http://127.0.0.1:1234/v1/models"
    assert seen["headers"].get("Authorization") == "Bearer local"  # dummy key for keyless local


def test_list_models_reports_connection_failure_as_hint(monkeypatch):
    import httpx

    def fake_get(url, **kwargs):
        raise httpx.ConnectError("refused")

    monkeypatch.setattr("httpx.get", fake_get)
    res = client.post("/settings/llm/models", json={"kind": "ollama"})
    assert res.status_code == 200  # degrades to a UI hint, not a 5xx
    body = res.json()
    assert body["models"] == []
    assert "11434" in body["error"]


def test_update_credential_keeps_secret_when_blank():
    res = client.post(
        "/settings/llm/credentials",
        json={"label": "A", "kind": "openai", "api_key": "key-9999", "default_model": "m"},
    )
    cred_id = res.json()["credentials"][0]["credential_id"]
    # update label only, api_key blank => keep existing
    res = client.post(
        "/settings/llm/credentials",
        json={"credential_id": cred_id, "label": "Renamed", "kind": "openai", "api_key": "", "default_model": "m2"},
    )
    cred = res.json()["credentials"][0]
    assert cred["label"] == "Renamed"
    assert cred["has_key"] is True
    assert cred["api_key_preview"].endswith("9999")
