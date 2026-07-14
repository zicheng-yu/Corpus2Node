from __future__ import annotations

import hashlib
import io
import uuid
import zipfile

from fastapi.testclient import TestClient

from corpus2node.api.app import app
from corpus2node.config import settings
from corpus2node.core.types import CourseSession
from corpus2node.storage import local

client = TestClient(app)


def test_create_and_get_session():
    response = client.post("/sessions", json={"course_title": "数据结构", "lecture_title": "树"})
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "draft"
    session_id = body["session_id"]

    fetched = client.get(f"/sessions/{session_id}")
    assert fetched.status_code == 200
    assert fetched.json()["course_title"] == "数据结构"


def test_rename_session_updates_lecture_title():
    body = client.post("/sessions", json={"course_title": "数据结构", "lecture_title": "树"}).json()
    session_id = body["session_id"]

    response = client.patch(f"/sessions/{session_id}", json={"lecture_title": "  图与最短路  "})
    assert response.status_code == 200
    assert response.json()["lecture_title"] == "图与最短路"

    fetched = client.get(f"/sessions/{session_id}")
    assert fetched.status_code == 200
    assert fetched.json()["lecture_title"] == "图与最短路"


def test_rename_session_rejects_empty_title():
    session_id = client.post("/sessions", json={"course_title": "DS", "lecture_title": "Trees"}).json()["session_id"]

    response = client.patch(f"/sessions/{session_id}", json={"lecture_title": " \n\t "})
    assert response.status_code == 400


def test_rename_course_updates_all_sessions_and_virtual_graph_session():
    first = client.post("/sessions", json={"course_title": "旧知识库", "lecture_title": "第一份资料"}).json()
    second = client.post("/sessions", json={"course_title": "旧知识库", "lecture_title": "第二份资料"}).json()
    other = client.post("/sessions", json={"course_title": "其它知识库", "lecture_title": "不应改名"}).json()
    virtual = CourseSession(course_title="旧知识库", lecture_title=f"{local.COURSE_GRAPH_LECTURE_PREFIX}旧知识库")
    local.save_session(virtual)

    response = client.patch(
        "/sessions/course/rename",
        json={"old_course_title": "旧知识库", "new_course_title": "新知识库"},
    )
    assert response.status_code == 200
    updated = {item["session_id"]: item for item in response.json()}
    assert set(updated) == {first["session_id"], second["session_id"], str(virtual.session_id)}
    assert all(item["course_title"] == "新知识库" for item in updated.values())
    assert updated[str(virtual.session_id)]["lecture_title"] == f"{local.COURSE_GRAPH_LECTURE_PREFIX}新知识库"

    assert client.get(f"/sessions/{first['session_id']}").json()["course_title"] == "新知识库"
    assert client.get(f"/sessions/{second['session_id']}").json()["course_title"] == "新知识库"
    assert client.get(f"/sessions/{other['session_id']}").json()["course_title"] == "其它知识库"
    assert local.find_course_session("新知识库") is not None
    assert local.find_course_session("旧知识库") is None


def test_rename_course_rejects_existing_target_name():
    client.post("/sessions", json={"course_title": "A", "lecture_title": "一"})
    client.post("/sessions", json={"course_title": "B", "lecture_title": "二"})

    response = client.patch("/sessions/course/rename", json={"old_course_title": "A", "new_course_title": "B"})
    assert response.status_code == 409


def test_rename_course_rejects_missing_source_name():
    response = client.patch("/sessions/course/rename", json={"old_course_title": "missing", "new_course_title": "missing"})
    assert response.status_code == 404


def test_upload_pdf_adds_source():
    session_id = client.post("/sessions", json={"course_title": "DS", "lecture_title": "Trees"}).json()["session_id"]
    files = {"file": ("lecture.pdf", b"%PDF-1.4 fake pdf bytes", "application/pdf")}
    response = client.post(f"/sessions/{session_id}/sources", files=files)
    assert response.status_code == 200
    assert response.json()["kind"] == "pdf"
    assert response.json()["status"] == "uploaded"

    session = client.get(f"/sessions/{session_id}").json()
    assert len(session["source_files"]) == 1
    assert session["source_files"][0]["filename"] == "lecture.pdf"
    assert session["source_files"][0]["content_sha256"] == hashlib.sha256(
        b"%PDF-1.4 fake pdf bytes"
    ).hexdigest()


def test_upload_markdown_adds_document_source():
    session_id = client.post("/sessions", json={"course_title": "DS", "lecture_title": "Trees"}).json()["session_id"]
    files = {"file": ("notes.md", "# 树\n\n二叉搜索树用于查找。".encode("utf-8"), "text/markdown")}
    response = client.post(f"/sessions/{session_id}/sources", files=files)
    assert response.status_code == 200
    assert response.json()["kind"] == "document"


def test_upload_sanitizes_filename_and_stores_by_source_id():
    session_id = client.post("/sessions", json={"course_title": "DS", "lecture_title": "Trees"}).json()["session_id"]
    files = {"file": ("../notes.md", "# 树".encode("utf-8"), "text/markdown")}
    response = client.post(f"/sessions/{session_id}/sources", files=files)
    assert response.status_code == 200
    source_id = response.json()["source_id"]

    session = client.get(f"/sessions/{session_id}").json()
    source = session["source_files"][0]
    assert source["filename"] == "notes.md"
    assert "storage_path" not in source
    assert "ingest_artifact_path" not in source

    stored = local.load_session(uuid.UUID(session_id)).source_files[0]
    assert stored.storage_path.endswith(f"/uploads/{source_id}.md")
    assert ".." not in stored.storage_path


def test_upload_rejects_file_over_configured_limit(monkeypatch):
    monkeypatch.setattr(settings, "max_upload_bytes", 4)
    session_id = client.post("/sessions", json={"course_title": "DS", "lecture_title": "Trees"}).json()["session_id"]
    files = {"file": ("large.md", b"12345", "text/markdown")}
    response = client.post(f"/sessions/{session_id}/sources", files=files)
    assert response.status_code == 413


def test_upload_image_accepted():
    session_id = client.post("/sessions", json={"course_title": "X", "lecture_title": "Y"}).json()["session_id"]
    files = {"file": ("diagram.png", b"\x89PNG\r\n\x1a\n", "image/png")}
    response = client.post(f"/sessions/{session_id}/sources", files=files)
    assert response.status_code == 200
    assert response.json()["kind"] == "image"


def test_upload_rejects_unsupported_type():
    session_id = client.post("/sessions", json={"course_title": "X", "lecture_title": "Y"}).json()["session_id"]
    files = {"file": ("malware.exe", b"\x00\x01", "application/octet-stream")}
    response = client.post(f"/sessions/{session_id}/sources", files=files)
    assert response.status_code == 400


def test_upload_rejects_extension_content_mismatch():
    session_id = client.post("/sessions", json={"course_title": "X", "lecture_title": "Y"}).json()["session_id"]
    response = client.post(
        f"/sessions/{session_id}/sources",
        files={"file": ("not-really.pdf", b"plain text", "application/pdf")},
    )
    assert response.status_code == 400
    assert "does not match" in response.json()["detail"]
    assert client.get(f"/sessions/{session_id}").json()["source_files"] == []


def test_upload_rejects_zip_disguised_as_office_document():
    session_id = client.post("/sessions", json={"course_title": "X", "lecture_title": "Y"}).json()["session_id"]
    payload = io.BytesIO()
    with zipfile.ZipFile(payload, "w") as archive:
        archive.writestr("unrelated.txt", "not a Word document")

    response = client.post(
        f"/sessions/{session_id}/sources",
        files={
            "file": (
                "not-really.docx",
                payload.getvalue(),
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            )
        },
    )

    assert response.status_code == 400
    assert "valid .docx" in response.json()["detail"]
    assert client.get(f"/sessions/{session_id}").json()["source_files"] == []


def test_get_missing_session_returns_404():
    response = client.get(f"/sessions/{uuid.uuid4()}")
    assert response.status_code == 404
