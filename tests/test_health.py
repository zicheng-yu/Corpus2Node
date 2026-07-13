from __future__ import annotations

from fastapi.testclient import TestClient

from corpus2node.api.app import app
from corpus2node.config import settings


def test_health() -> None:
    client = TestClient(app)
    response = client.get("/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["service"] == "corpus2node"


def test_contract_types_import() -> None:
    # The copied data contract must import cleanly under the new package name.
    from corpus2node.core.types import ChatDocument, ExamDocument, GraphArtifact, NoteDocument

    assert all(t.__name__ for t in (GraphArtifact, NoteDocument, ExamDocument, ChatDocument))


def test_optional_api_auth(monkeypatch) -> None:
    monkeypatch.setattr(settings, "api_auth_token", "secret")
    client = TestClient(app)
    assert client.get("/health").status_code == 200
    assert client.get("/sessions").status_code == 401
    assert client.get("/sessions", headers={"Authorization": "Bearer secret"}).status_code == 200


def test_production_error_response_hides_traceback(monkeypatch) -> None:
    monkeypatch.setattr(settings, "app_env", "production")
    monkeypatch.setattr(settings, "debug_tracebacks", True)
    monkeypatch.setattr(settings, "require_auth_in_production", False)
    monkeypatch.setattr(settings, "allow_ephemeral_storage", True)

    @app.get("/__test_boom")
    async def __test_boom():
        raise RuntimeError("secret failure detail")

    client = TestClient(app, raise_server_exceptions=False)
    response = client.get("/__test_boom")
    assert response.status_code == 500
    body = response.json()
    assert body["detail"] == "Internal server error."
    assert "type" not in body
    assert "traceback" not in body


def test_production_requires_auth_configuration(monkeypatch) -> None:
    monkeypatch.setattr(settings, "app_env", "production")
    monkeypatch.setattr(settings, "api_auth_token", "")
    monkeypatch.setattr(settings, "require_auth_in_production", True)
    monkeypatch.setattr(settings, "allow_ephemeral_storage", True)
    client = TestClient(app)
    assert client.get("/health").status_code == 200
    response = client.get("/sessions")
    assert response.status_code == 503
    assert "API_AUTH_TOKEN" in response.json()["detail"]
