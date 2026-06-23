from __future__ import annotations

from fastapi.testclient import TestClient

from corpus2node.api.app import app

client = TestClient(app)


def test_demo_ui_is_served():
    response = client.get("/ui/")
    assert response.status_code == 200
    assert "Corpus2Node" in response.text


def test_health_still_ok():
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"
