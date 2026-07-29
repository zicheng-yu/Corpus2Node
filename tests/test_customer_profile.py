from __future__ import annotations

from fastapi.testclient import TestClient

from corpus2node.api.app import app
from corpus2node.config import settings
from corpus2node.customization.profile import clear_profile_cache, load_customer_profile


def test_default_customer_profile_endpoint() -> None:
    clear_profile_cache()
    client = TestClient(app)
    response = client.get("/customer-profile")
    assert response.status_code == 200
    body = response.json()
    assert body["customer_id"] == "default"
    assert set(body["personas"]) == {"executive", "researcher", "operator"}
    assert body["personas"]["operator"]["landing"] == "/"


def test_longxin_customer_profile_loads_from_repo_package(monkeypatch) -> None:
    monkeypatch.setattr(settings, "customer_profile", "longxin")
    clear_profile_cache()
    profile = load_customer_profile("longxin")
    assert profile.customer_id == "longxin"
    assert profile.brand.product_name == "龙芯知识工作台"
    assert profile.landing_for("executive") == "/discover?mode=scientific"
    assert profile.landing_for("researcher") == "/discover?mode=scientific&focus=evidence"
    assert profile.landing_for("operator") == "/new"

    client = TestClient(app)
    response = client.get("/api/customer-profile")
    assert response.status_code == 200
    body = response.json()
    assert body["customer_id"] == "longxin"
    assert body["personas"]["operator"]["landing"] == "/new"
    clear_profile_cache()
