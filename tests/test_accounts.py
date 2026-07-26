from __future__ import annotations

import asyncio
from datetime import timedelta
from pathlib import Path
from urllib.parse import parse_qs
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from corpus2node.accounts.database import dispose_db, init_db, session_factory
from corpus2node.accounts.models import Project, ProjectRevision, Resource, ShareLink
from corpus2node.accounts.security import hash_token
from corpus2node.accounts.schemas import Principal
from corpus2node.accounts.service import (
    create_invitation,
    create_organization,
    record_usage,
    usage_count,
)
from corpus2node.api.app import app
from corpus2node.api.routes.shares import _public_discovery_report, _public_scientific_report
from corpus2node.api.routes.auth import _ATTEMPTS
from corpus2node.config import settings
from corpus2node.admin import invite_user
from corpus2node.core.clock import utcnow
from corpus2node.core.types import (
    ChatDocument,
    ChatMessage,
    DiscoveryEvidence,
    DiscoveryFinding,
    DiscoveryParticipant,
    DiscoveryReport,
    GraphArtifact,
    InnovationProposal,
    NoteDocument,
    SourceKind,
    TestDocument as GeneratedTestDocument,
)
from corpus2node.llm import store
from corpus2node.scientific.schemas import (
    RDDecisionCard,
    ScientificClaim,
    ScientificEvidence,
    ScientificInsight,
    ScientificInsightType,
    ScientificReport,
)
from corpus2node.storage import local

PASSWORD = "correct-horse-battery-staple"


async def _bootstrap() -> tuple[str, str]:
    await init_db()
    async with session_factory()() as db:
        organization = await create_organization(db, name="Platform", plan_code="team_beta")
        _, token = await create_invitation(
            db,
            organization_id=organization.organization_id,
            email="platform@example.com",
            role="owner",
            invited_by_user_id=None,
            make_platform_admin=True,
        )
        await db.commit()
        return organization.organization_id, token


@pytest.fixture
def account_env(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "auth_mode", "accounts")
    monkeypatch.setattr(settings, "account_product_mode", "teams")
    monkeypatch.setattr(settings, "database_url", f"sqlite+aiosqlite:///{tmp_path / 'accounts.db'}")
    monkeypatch.setattr(settings, "database_auto_create", True)
    monkeypatch.setattr(settings, "public_app_url", "http://testserver")
    monkeypatch.setattr(settings, "auth_cookie_secure", False)
    monkeypatch.setattr(settings, "project_refresh_debounce_seconds", 0.0)
    _ATTEMPTS.clear()
    asyncio.run(dispose_db())
    organization_id, token = asyncio.run(_bootstrap())
    asyncio.run(dispose_db())
    yield organization_id, token
    asyncio.run(dispose_db())
    _ATTEMPTS.clear()


def _activate(client: TestClient, token: str, name: str = "User") -> dict:
    response = client.post(
        "/auth/activate",
        json={"token": token, "display_name": name, "password": PASSWORD},
    )
    assert response.status_code == 200, response.text
    cookies = response.headers.get_list("set-cookie")
    assert any("c2n_session=" in value and "HttpOnly" in value and "SameSite=lax" in value for value in cookies)
    assert any("c2n_csrf=" in value and "SameSite=lax" in value for value in cookies)
    return response.json()


def _headers(
    client: TestClient,
    organization_id: str,
    *,
    origin: str | None = "http://testserver",
) -> dict[str, str]:
    headers = {
        "X-CSRF-Token": client.cookies.get("c2n_csrf"),
        "X-Organization-ID": organization_id,
    }
    if origin is not None:
        headers["Origin"] = origin
    return headers


def _token_from_url(url: str) -> str:
    fragment = url.split("#", 1)[1]
    return parse_qs(fragment)["token"][0]


def _provision(client: TestClient, platform_org_id: str, name: str, email: str, plan: str = "team_beta"):
    response = client.post(
        "/admin/organizations",
        json={"name": name, "owner_email": email, "plan_code": plan},
        headers=_headers(client, platform_org_id),
    )
    assert response.status_code == 200, response.text
    body = response.json()
    return body["organization"]["organization_id"], _token_from_url(
        body["owner_invitation"]["activation_url"]
    )


def test_activation_login_csrf_logout_and_password_hash(account_env):
    platform_org_id, token = account_env
    client = TestClient(app)
    current = _activate(client, token, "Platform Admin")
    assert current["is_platform_admin"] is True
    assert client.cookies.get("c2n_session")
    assert client.cookies.get("c2n_csrf")

    reused = TestClient(app).post(
        "/auth/activate",
        json={"token": token, "display_name": "Again", "password": PASSWORD},
    )
    assert reused.status_code == 400

    missing_csrf = client.post(
        "/projects",
        json={"name": "Blocked"},
        headers={"X-Organization-ID": platform_org_id},
    )
    assert missing_csrf.status_code == 403
    missing_origin = client.post(
        "/projects",
        json={"name": "Blocked"},
        headers=_headers(client, platform_org_id, origin=None),
    )
    assert missing_origin.status_code == 403
    bad_origin = client.post(
        "/projects",
        json={"name": "Blocked"},
        headers=_headers(client, platform_org_id, origin="https://evil.example"),
    )
    assert bad_origin.status_code == 403
    created = client.post(
        "/projects",
        json={"name": "Allowed"},
        headers=_headers(client, platform_org_id, origin="http://testserver"),
    )
    assert created.status_code == 200

    login_client = TestClient(app)
    assert login_client.post(
        "/auth/login", json={"email": "platform@example.com", "password": "wrong-password-123"}
    ).status_code == 401
    assert login_client.post(
        "/auth/login", json={"email": "platform@example.com", "password": PASSWORD}
    ).status_code == 200

    changed_password = "new-correct-horse-battery-staple"
    changed = client.post(
        "/auth/change-password",
        json={"current_password": PASSWORD, "new_password": changed_password},
        headers=_headers(client, platform_org_id),
    )
    assert changed.status_code == 200
    assert client.get("/auth/me").status_code == 200
    assert login_client.get("/auth/me").status_code == 401
    assert login_client.post(
        "/auth/login", json={"email": "platform@example.com", "password": PASSWORD}
    ).status_code == 401
    assert login_client.post(
        "/auth/login", json={"email": "platform@example.com", "password": changed_password}
    ).status_code == 200

    logout = login_client.post(
        "/auth/logout",
        headers=_headers(login_client, platform_org_id),
    )
    assert logout.status_code == 200
    assert login_client.get("/auth/me").status_code == 401


def test_production_session_cookie_can_be_secure(account_env, monkeypatch):
    _, token = account_env
    monkeypatch.setattr(settings, "auth_cookie_secure", True)
    client = TestClient(app, base_url="https://testserver")
    response = client.post(
        "/auth/activate",
        json={"token": token, "display_name": "Secure User", "password": PASSWORD},
    )
    assert response.status_code == 200
    session_cookie = next(
        value for value in response.headers.get_list("set-cookie") if value.startswith("c2n_session=")
    )
    assert "HttpOnly" in session_cookie
    assert "Secure" in session_cookie
    assert "SameSite=lax" in session_cookie


def test_invite_user_cli_creates_one_private_workspace(account_env, monkeypatch):
    monkeypatch.setattr(settings, "account_product_mode", "personal")
    activation_url = asyncio.run(invite_user("private@example.com", "Private User"))
    client = TestClient(app)
    current = _activate(client, _token_from_url(activation_url), "Private User")
    assert len(current["memberships"]) == 1
    assert current["memberships"][0]["role"] == "owner"
    assert current["memberships"][0]["organization_name"] == "Private User 的资料库"


def test_personal_mode_isolates_workspace_content_and_byok(account_env, monkeypatch):
    platform_org_id, token = account_env
    platform = TestClient(app)
    _activate(platform, token, "Platform")
    owner_org_id, owner_token = _provision(
        platform,
        platform_org_id,
        "Personal Owner Workspace",
        "personal-owner@example.com",
    )
    owner = TestClient(app)
    owner_user = _activate(owner, owner_token, "Personal Owner")
    member_invite = owner.post(
        f"/organizations/{owner_org_id}/invitations",
        json={"email": "personal-member@example.com", "role": "member"},
        headers=_headers(owner, owner_org_id),
    )
    assert member_invite.status_code == 200

    monkeypatch.setattr(settings, "account_product_mode", "personal")
    owner_me = owner.get("/auth/me")
    assert owner_me.status_code == 200
    assert [value["organization_id"] for value in owner_me.json()["memberships"]] == [owner_org_id]

    member = TestClient(app)
    member_user = _activate(
        member,
        _token_from_url(member_invite.json()["activation_url"]),
        "Personal Member",
    )
    member_org_id = member_user["active_organization_id"]
    assert member_org_id != owner_org_id
    assert len(member_user["memberships"]) == 1
    assert member_user["memberships"][0]["role"] == "owner"

    assert owner.get("/organizations").json()[0]["organization_id"] == owner_org_id
    assert member.get("/organizations").json()[0]["organization_id"] == member_org_id
    assert owner.get(f"/organizations/{owner_org_id}/members").status_code == 404

    project = owner.post(
        "/projects",
        json={"name": "Private Research"},
        headers=_headers(owner, owner_org_id),
    )
    session = owner.post(
        "/sessions",
        json={
            "course_title": "Private Research",
            "lecture_title": "Owner only",
            "project_id": project.json()["project_id"],
        },
        headers=_headers(owner, owner_org_id),
    )
    assert session.status_code == 200
    assert member.get("/sessions", headers={"X-Organization-ID": owner_org_id}).json() == []

    owner_settings = owner.post(
        "/settings/llm/credentials",
        json={
            "label": "Owner API",
            "kind": "openai",
            "base_url": "https://api.owner.example/v1",
            "api_key": "owner-secret-key",
            "default_model": "owner-model",
        },
        headers=_headers(owner, owner_org_id),
    )
    assert owner_settings.status_code == 200
    assert member.get("/settings/llm").json()["credentials"] == []

    member_settings = member.post(
        "/settings/llm/credentials",
        json={
            "label": "Member API",
            "kind": "openai",
            "base_url": "https://api.member.example/v1",
            "api_key": "member-secret-key",
            "default_model": "member-model",
        },
        headers=_headers(member, member_org_id),
    )
    assert member_settings.status_code == 200
    assert [value["label"] for value in owner.get("/settings/llm").json()["credentials"]] == ["Owner API"]
    assert [value["label"] for value in member.get("/settings/llm").json()["credentials"]] == ["Member API"]
    assert "owner-secret-key" in store.path_for_user(owner_user["user_id"]).read_text(encoding="utf-8")
    assert "member-secret-key" in store.path_for_user(member_user["user_id"]).read_text(encoding="utf-8")
    assert store.path_for_user(owner_user["user_id"]).stat().st_mode & 0o777 == 0o600


def test_cross_tenant_role_matrix_and_private_chat(account_env):
    platform_org_id, token = account_env
    platform = TestClient(app)
    _activate(platform, token, "Platform")
    org_a, token_a = _provision(platform, platform_org_id, "Lab A", "owner-a@example.com")
    org_b, token_b = _provision(platform, platform_org_id, "Lab B", "owner-b@example.com")

    owner_a = TestClient(app)
    owner_a_user = _activate(owner_a, token_a, "Owner A")
    owner_b = TestClient(app)
    _activate(owner_b, token_b, "Owner B")

    project = owner_a.post(
        "/projects",
        json={"name": "Shared Research", "kind": "scientific"},
        headers=_headers(owner_a, org_a),
    )
    assert project.status_code == 200
    project_id = project.json()["project_id"]
    session = owner_a.post(
        "/sessions",
        json={"course_title": "compat", "lecture_title": "Paper A", "project_id": project_id},
        headers=_headers(owner_a, org_a),
    )
    assert session.status_code == 200
    session_id = session.json()["session_id"]

    assert owner_b.get(f"/sessions/{session_id}", headers={"X-Organization-ID": org_b}).status_code == 404
    assert owner_b.get("/sessions", headers={"X-Organization-ID": org_b}).json() == []
    assert owner_b.get(f"/projects/{project_id}", headers={"X-Organization-ID": org_b}).status_code == 404
    isolated_requests = [
        ("GET", f"/graph/{session_id}", None),
        ("GET", f"/graph/{session_id}/subgraph?concept_id=missing", None),
        ("POST", "/graph/search", {"session_id": session_id, "query": "evidence"}),
        ("GET", f"/workflow/{session_id}/run", None),
        ("POST", "/workflow/stream", {"session_id": session_id}),
        ("GET", f"/chat/{session_id}", None),
        ("POST", "/chat/message", {"session_id": session_id, "message": "secret"}),
        ("POST", "/generate_notes/stream", {"session_id": session_id}),
        ("GET", f"/notes/{session_id}/stream", None),
        ("POST", "/generate_test/stream", {"session_id": session_id}),
        ("GET", f"/test/{session_id}/stream", None),
        ("POST", "/scientific/parse", {"session_id": session_id, "source_ids": []}),
        ("GET", f"/scientific/documents/{session_id}", None),
        ("GET", f"/export/{session_id}/md", None),
    ]
    for method, url, json_body in isolated_requests:
        response = owner_b.request(
            method,
            url,
            json=json_body,
            headers=_headers(owner_b, org_b),
        )
        assert response.status_code == 404, (method, url, response.text)

    invite = owner_a.post(
        f"/organizations/{org_a}/invitations",
        json={"email": "viewer-a@example.com", "role": "viewer"},
        headers=_headers(owner_a, org_a),
    )
    assert invite.status_code == 200
    viewer = TestClient(app)
    viewer_user = _activate(viewer, _token_from_url(invite.json()["activation_url"]), "Viewer")
    assert len(viewer.get("/sessions", headers={"X-Organization-ID": org_a}).json()) == 1
    assert viewer.post(
        "/sessions",
        json={"course_title": "X", "lecture_title": "Y", "project_id": project_id},
        headers=_headers(viewer, org_a),
    ).status_code == 403

    local.save_chat(
        ChatDocument(
            session_id=UUID(session_id),
            messages=[ChatMessage(role="user", content="owner private")],
        ),
        f"{org_a}/{owner_a_user['user_id']}",
    )
    owner_history = owner_a.get(f"/chat/{session_id}", headers={"X-Organization-ID": org_a})
    viewer_history = viewer.get(f"/chat/{session_id}", headers={"X-Organization-ID": org_a})
    assert owner_history.json()["messages"][0]["content"] == "owner private"
    assert viewer_history.json()["messages"] == []
    owner_key = f"{org_a}/{owner_a_user['user_id']}"
    local.save_note(
        NoteDocument(
            session_id=UUID(session_id),
            title="Owner note",
            topic="Private",
            summary="Only owner",
        ),
        owner_key,
    )
    local.save_test(
        GeneratedTestDocument(session_id=UUID(session_id), title="Owner test"),
        owner_key,
    )
    assert owner_a.get(f"/notes/{session_id}", headers={"X-Organization-ID": org_a}).status_code == 200
    assert viewer.get(f"/notes/{session_id}", headers={"X-Organization-ID": org_a}).status_code == 404
    assert owner_a.get(f"/test/{session_id}", headers={"X-Organization-ID": org_a}).status_code == 200
    assert viewer.get(f"/test/{session_id}", headers={"X-Organization-ID": org_a}).status_code == 404
    assert owner_a_user["user_id"] != viewer_user["user_id"]

    member_invite = owner_a.post(
        f"/organizations/{org_a}/invitations",
        json={"email": "member-a@example.com", "role": "member"},
        headers=_headers(owner_a, org_a),
    )
    member = TestClient(app)
    member_user = _activate(member, _token_from_url(member_invite.json()["activation_url"]), "Member")
    assert member.post(
        "/projects",
        json={"name": "Member cannot manage projects"},
        headers=_headers(member, org_a),
    ).status_code == 403
    assert member.post(
        "/sessions",
        json={"course_title": "Cannot create implicitly", "lecture_title": "Paper"},
        headers=_headers(member, org_a),
    ).status_code == 403
    assert member.post(
        f"/organizations/{org_a}/invitations",
        json={"email": "blocked@example.com", "role": "member"},
        headers=_headers(member, org_a),
    ).status_code == 403

    admin_invite = owner_a.post(
        f"/organizations/{org_a}/invitations",
        json={"email": "admin-a@example.com", "role": "admin"},
        headers=_headers(owner_a, org_a),
    )
    admin = TestClient(app)
    _activate(admin, _token_from_url(admin_invite.json()["activation_url"]), "Admin")
    assert admin.post(
        f"/organizations/{org_a}/invitations",
        json={"email": "admin-can-invite@example.com", "role": "viewer"},
        headers=_headers(admin, org_a),
    ).status_code == 200
    assert admin.post(
        f"/organizations/{org_a}/invitations",
        json={"email": "admin-cannot-elevate@example.com", "role": "admin"},
        headers=_headers(admin, org_a),
    ).status_code == 403
    assert admin.patch(
        f"/organizations/{org_a}/members/{member_user['user_id']}",
        json={"role": "viewer"},
        headers=_headers(admin, org_a),
    ).status_code == 403
    assert owner_a.patch(
        f"/organizations/{org_a}/members/{member_user['user_id']}",
        json={"role": "viewer"},
        headers=_headers(owner_a, org_a),
    ).status_code == 200

    reset = platform.post(
        f"/admin/users/{owner_a_user['user_id']}/password-reset",
        headers=_headers(platform, platform_org_id),
    )
    assert reset.status_code == 200
    reset_token = _token_from_url(reset.json()["activation_url"])
    replacement_password = "replacement-horse-battery-staple"
    reset_client = TestClient(app)
    activated = reset_client.post(
        "/auth/activate",
        json={
            "token": reset_token,
            "display_name": "Owner A",
            "password": replacement_password,
        },
    )
    assert activated.status_code == 200
    assert owner_a.get("/auth/me").status_code == 401
    assert TestClient(app).post(
        "/auth/activate",
        json={"token": reset_token, "display_name": "Again", "password": replacement_password},
    ).status_code == 400


def test_member_can_archive_team_session_but_viewer_cannot(account_env, monkeypatch):
    monkeypatch.setattr(
        "corpus2node.api.routes.sessions.schedule_project_refresh",
        lambda *_args, **_kwargs: None,
    )
    platform_org_id, token = account_env
    platform = TestClient(app)
    _activate(platform, token, "Platform")
    org_id, owner_token = _provision(
        platform,
        platform_org_id,
        "Archive Lab",
        "archive-owner@example.com",
    )
    owner = TestClient(app)
    _activate(owner, owner_token, "Owner")
    project = owner.post(
        "/projects",
        json={"name": "Archive Project"},
        headers=_headers(owner, org_id),
    )
    session = owner.post(
        "/sessions",
        json={
            "course_title": "Archive Project",
            "lecture_title": "Shared material",
            "project_id": project.json()["project_id"],
        },
        headers=_headers(owner, org_id),
    )
    session_id = session.json()["session_id"]

    member_invite = owner.post(
        f"/organizations/{org_id}/invitations",
        json={"email": "archive-member@example.com", "role": "member"},
        headers=_headers(owner, org_id),
    )
    viewer_invite = owner.post(
        f"/organizations/{org_id}/invitations",
        json={"email": "archive-viewer@example.com", "role": "viewer"},
        headers=_headers(owner, org_id),
    )
    member = TestClient(app)
    viewer = TestClient(app)
    _activate(member, _token_from_url(member_invite.json()["activation_url"]), "Member")
    _activate(viewer, _token_from_url(viewer_invite.json()["activation_url"]), "Viewer")

    assert viewer.delete(
        f"/sessions/{session_id}",
        headers=_headers(viewer, org_id),
    ).status_code == 403
    assert member.delete(
        f"/sessions/{session_id}",
        headers=_headers(member, org_id),
    ).status_code == 200
    assert member.get("/sessions", headers={"X-Organization-ID": org_id}).json() == []
    assert local.load_session(UUID(session_id)).lecture_title == "Shared material"


async def _install_revision(org_id: str, project_id: str, creator_id: str) -> str:
    await init_db()
    graph = GraphArtifact(session_id=uuid4())
    path = Path(settings.local_storage_path) / "projects" / project_id / "revisions" / "1" / "graph.json"
    local.write_text_atomic(path, graph.model_dump_json(indent=2))
    async with session_factory()() as db:
        revision = ProjectRevision(
            project_id=project_id,
            revision_number=1,
            fingerprint="f" * 64,
            status="ready",
            graph_artifact_path=str(path),
            created_by_user_id=creator_id,
            completed_at=utcnow(),
        )
        db.add(revision)
        await db.flush()
        project = await db.get(Project, project_id)
        assert project is not None
        project.latest_revision_id = revision.revision_id
        db.add(
            Resource(
                resource_type="project_revision",
                resource_key=revision.revision_id,
                organization_id=org_id,
                project_id=project_id,
                artifact_path=str(path),
            )
        )
        await db.commit()
        return revision.revision_id


async def _stored_share_hash(share_id: str) -> str:
    await init_db()
    async with session_factory()() as db:
        value = await db.get(ShareLink, share_id)
        assert value is not None
        return value.token_hash


async def _install_report_resource(organization_id: str, resource_type: str, resource_key: str, path: Path) -> None:
    await init_db()
    async with session_factory()() as db:
        db.add(
            Resource(
                resource_type=resource_type,
                resource_key=resource_key,
                organization_id=organization_id,
                artifact_path=str(path),
            )
        )
        await db.commit()


def test_unified_discovery_history_is_tenant_scoped(account_env):
    platform_org_id, token = account_env
    platform = TestClient(app)
    _activate(platform, token, "Platform")
    org_a, token_a = _provision(platform, platform_org_id, "History A", "history-a@example.com")
    org_b, token_b = _provision(platform, platform_org_id, "History B", "history-b@example.com")
    owner_a = TestClient(app)
    owner_b = TestClient(app)
    _activate(owner_a, token_a, "Owner A")
    _activate(owner_b, token_b, "Owner B")

    discovery = DiscoveryReport(title="A 的跨资料发现")
    scientific = ScientificReport(title_zh="B 的科研证据", session_ids=[uuid4()])
    discovery_path = local.save_discovery_report(discovery)
    scientific_path = local.save_scientific_report(scientific)
    asyncio.run(
        _install_report_resource(org_a, "discovery_report", discovery.discovery_id, discovery_path)
    )
    asyncio.run(
        _install_report_resource(org_b, "scientific_report", scientific.report_id, scientific_path)
    )

    history_a = owner_a.get("/discovery/history", headers={"X-Organization-ID": org_a})
    history_b = owner_b.get("/discovery/history", headers={"X-Organization-ID": org_b})

    assert [item["title"] for item in history_a.json()] == ["A 的跨资料发现"]
    assert [item["title"] for item in history_b.json()] == ["B 的科研证据"]


def test_share_snapshot_hash_revocation_and_archive(account_env):
    platform_org_id, platform_token = account_env
    platform = TestClient(app)
    _activate(platform, platform_token, "Platform")
    org_id, owner_token = _provision(platform, platform_org_id, "Share Lab", "share-owner@example.com")
    owner = TestClient(app)
    owner_user = _activate(owner, owner_token, "Share Owner")
    project = owner.post(
        "/projects",
        json={"name": "Share Project"},
        headers=_headers(owner, org_id),
    ).json()

    asyncio.run(dispose_db())
    revision_id = asyncio.run(_install_revision(org_id, project["project_id"], owner_user["user_id"]))
    asyncio.run(dispose_db())

    created = owner.post(
        "/shares",
        json={"resource_type": "project_revision", "resource_key": revision_id, "expires_in_days": 7},
        headers=_headers(owner, org_id),
    )
    assert created.status_code == 200, created.text
    body = created.json()
    raw_token = _token_from_url(body["share_url"])
    graph_path = Path(settings.local_storage_path) / "projects" / project["project_id"] / "revisions" / "1" / "graph.json"
    original_graph = GraphArtifact.model_validate_json(graph_path.read_text(encoding="utf-8"))
    changed_graph = GraphArtifact(session_id=uuid4())
    local.write_text_atomic(graph_path, changed_graph.model_dump_json(indent=2))
    asyncio.run(dispose_db())
    stored_hash = asyncio.run(_stored_share_hash(body["share_id"]))
    asyncio.run(dispose_db())
    assert stored_hash == hash_token(raw_token)
    assert stored_hash != raw_token

    public = TestClient(app).post("/public/shares/resolve", json={"token": raw_token})
    assert public.status_code == 200
    payload = public.json()["payload"]
    assert "graph" in payload
    assert payload["graph"]["session_id"] == str(original_graph.session_id)
    assert payload["graph"]["session_id"] != str(changed_graph.session_id)
    assert "artifact_path" not in public.text
    assert "embedding" not in public.text

    archived = owner.delete(f"/projects/{project['project_id']}", headers=_headers(owner, org_id))
    assert archived.status_code == 200
    assert TestClient(app).post("/public/shares/resolve", json={"token": raw_token}).status_code == 404

    revoked = owner.delete(f"/shares/{body['share_id']}", headers=_headers(owner, org_id))
    assert revoked.status_code == 200
    assert TestClient(app).post("/public/shares/resolve", json={"token": raw_token}).status_code == 404


def test_free_quota_and_inactive_plan_are_read_only(account_env):
    platform_org_id, token = account_env
    platform = TestClient(app)
    _activate(platform, token, "Platform")
    org_id, owner_token = _provision(platform, platform_org_id, "Free Lab", "free@example.com", plan="free")
    owner = TestClient(app)
    owner_user = _activate(owner, owner_token, "Free Owner")
    first = owner.post("/projects", json={"name": "One"}, headers=_headers(owner, org_id))
    assert first.status_code == 200
    readable_session = owner.post(
        "/sessions",
        json={
            "course_title": "One",
            "lecture_title": "Readable after downgrade",
            "project_id": first.json()["project_id"],
        },
        headers=_headers(owner, org_id),
    )
    assert readable_session.status_code == 200
    second = owner.post("/projects", json={"name": "Two"}, headers=_headers(owner, org_id))
    assert second.status_code == 429
    invite = owner.post(
        f"/organizations/{org_id}/invitations",
        json={"email": "extra@example.com", "role": "member"},
        headers=_headers(owner, org_id),
    )
    assert invite.status_code == 429
    asyncio.run(dispose_db())
    assert asyncio.run(_record_usage_idempotently(org_id, owner_user["user_id"])) == 1
    asyncio.run(dispose_db())

    downgraded = platform.patch(
        f"/admin/organizations/{org_id}/plan",
        json={"plan_code": "free", "plan_status": "inactive", "entitlement_overrides": {}},
        headers=_headers(platform, platform_org_id),
    )
    assert downgraded.status_code == 200
    read_only = owner.post(
        "/sessions",
        json={"course_title": "One", "lecture_title": "Cannot write", "project_id": first.json()["project_id"]},
        headers=_headers(owner, org_id),
    )
    assert read_only.status_code == 403
    session_id = readable_session.json()["session_id"]
    assert owner.get(f"/sessions/{session_id}", headers={"X-Organization-ID": org_id}).status_code == 200
    assert owner.delete(f"/chat/{session_id}", headers=_headers(owner, org_id)).status_code == 403
    assert owner.put(
        "/settings/prompts",
        json={"global_instructions": "cannot change"},
        headers=_headers(owner, org_id),
    ).status_code == 403


async def _expire_invitation(token: str) -> None:
    await init_db()
    from corpus2node.accounts.models import Invitation

    async with session_factory()() as db:
        invitation = await db.scalar(select(Invitation).where(Invitation.token_hash == hash_token(token)))
        assert invitation is not None
        invitation.expires_at = utcnow() - timedelta(seconds=1)
        await db.commit()


async def _record_usage_idempotently(organization_id: str, user_id: str) -> int:
    await init_db()
    principal = Principal(
        user_id=user_id,
        email="usage@example.com",
        display_name="Usage",
        organization_id=organization_id,
        role="owner",
    )
    async with session_factory()() as db:
        for _ in range(2):
            await record_usage(
                db,
                principal,
                idempotency_key="same-top-level-task",
                metric="ai_task",
                purpose="graph",
            )
        await db.commit()
        return await usage_count(db, organization_id, "ai_task")


def test_expired_invitation_and_login_rate_limit(account_env):
    platform_org_id, platform_token = account_env
    platform = TestClient(app)
    _activate(platform, platform_token, "Platform")
    _, invitation_token = _provision(platform, platform_org_id, "Expired Lab", "expired@example.com")
    asyncio.run(dispose_db())
    asyncio.run(_expire_invitation(invitation_token))
    asyncio.run(dispose_db())
    expired = TestClient(app).post(
        "/auth/activate",
        json={"token": invitation_token, "display_name": "Expired", "password": PASSWORD},
    )
    assert expired.status_code == 400

    client = TestClient(app)
    statuses = [
        client.post(
            "/auth/login",
            json={"email": "rate-limit@example.com", "password": "wrong-password-123"},
        ).status_code
        for _ in range(11)
    ]
    assert statuses[-1] == 429


def test_public_report_whitelists_remove_internal_resource_identifiers():
    session_id = uuid4()
    scientific = ScientificReport(
        title_zh="Evidence",
        session_ids=[session_id],
        claims=[
            ScientificClaim(
                session_id=session_id,
                claim_type="result",
                statement_zh="结论",
                evidence_ids=["e-1"],
            )
        ],
        evidence=[
            ScientificEvidence(
                evidence_id="e-1",
                session_id=session_id,
                source_id="source-secret",
                source_type=SourceKind.document,
                chunk_id="chunk-secret",
                locator="第 2 页",
                snippet="证据摘录",
            )
        ],
        insights=[
            ScientificInsight(
                insight_type=ScientificInsightType.research_gap,
                title_zh="空白",
                summary_zh="尚待验证",
                related_session_ids=[session_id],
            )
        ],
        decision_cards=[
            RDDecisionCard(
                title_zh="机会",
                recommendation_zh="验证",
                rationale_zh="有证据",
                next_experiment_zh="小规模实验",
            )
        ],
    )
    scientific_payload = _public_scientific_report(scientific)
    scientific_text = str(scientific_payload)
    assert str(session_id) not in scientific_text
    assert "source-secret" not in scientific_text
    assert "chunk-secret" not in scientific_text
    assert "证据摘录" in scientific_text

    participant = DiscoveryParticipant(
        session_id=session_id,
        course_title="课题",
        lecture_title="论文",
        concept_id="concept-secret",
        concept_name="方法",
    )
    evidence = DiscoveryEvidence(
        session_id=session_id,
        course_title="课题",
        lecture_title="论文",
        concept_id="concept-secret",
        concept_name="方法",
        chunk_id="chunk-secret",
        source_id="source-secret",
        locator="第 3 页",
        snippet="发现证据",
    )
    discovery = DiscoveryReport(
        session_ids=[session_id],
        findings=[DiscoveryFinding(title="联系", summary="有联系", participants=[participant], evidence=[evidence])],
        proposals=[InnovationProposal(title="提案", sources=[participant], evidence=[evidence])],
    )
    discovery_payload = _public_discovery_report(discovery)
    discovery_text = str(discovery_payload)
    assert str(session_id) not in discovery_text
    assert "concept-secret" not in discovery_text
    assert "chunk-secret" not in discovery_text
    assert "source-secret" not in discovery_text
    assert "发现证据" in discovery_text
