from __future__ import annotations

from fastapi.testclient import TestClient

from corpus2node.api.app import app


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
