from __future__ import annotations

import uuid

from fastapi.testclient import TestClient

from corpus2node.api.app import app

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


def test_upload_markdown_adds_document_source():
    session_id = client.post("/sessions", json={"course_title": "DS", "lecture_title": "Trees"}).json()["session_id"]
    files = {"file": ("notes.md", "# 树\n\n二叉搜索树用于查找。".encode("utf-8"), "text/markdown")}
    response = client.post(f"/sessions/{session_id}/sources", files=files)
    assert response.status_code == 200
    assert response.json()["kind"] == "document"


def test_upload_image_accepted():
    session_id = client.post("/sessions", json={"course_title": "X", "lecture_title": "Y"}).json()["session_id"]
    files = {"file": ("diagram.png", b"\x89PNG\r\n", "image/png")}
    response = client.post(f"/sessions/{session_id}/sources", files=files)
    assert response.status_code == 200
    assert response.json()["kind"] == "image"


def test_upload_rejects_unsupported_type():
    session_id = client.post("/sessions", json={"course_title": "X", "lecture_title": "Y"}).json()["session_id"]
    files = {"file": ("malware.exe", b"\x00\x01", "application/octet-stream")}
    response = client.post(f"/sessions/{session_id}/sources", files=files)
    assert response.status_code == 400


def test_get_missing_session_returns_404():
    response = client.get(f"/sessions/{uuid.uuid4()}")
    assert response.status_code == 404
