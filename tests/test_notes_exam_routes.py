from __future__ import annotations

import uuid

from fastapi.testclient import TestClient

from corpus2node.api.app import app
from corpus2node.config import settings
from corpus2node.core.types import (
    ChatDocument,
    ChatMessage,
    CourseSession,
    EvidenceChunk,
    IngestArtifact,
    NoteDocument,
    NoteSection,
    SourceKind,
    TestChoice as ChoiceModel,
    TestDocument as DocumentModel,
    TestQuestion as QuestionModel,
)
from corpus2node.graph.build import build_graph_artifact
from corpus2node.graph.schemas import ExtractedConcept, GraphExtractionResult
from corpus2node.index.embeddings import get_embeddings
from corpus2node.storage import local

client = TestClient(app)


def _seed_graph() -> uuid.UUID:
    settings.embed_provider = "hashing"  # dependency-free embeddings for routes
    emb = get_embeddings()
    session = CourseSession(course_title="c", lecture_title="l")
    chunks = [
        EvidenceChunk(
            chunk_id="s-c0", source_id="s", source_type=SourceKind.pdf,
            text="二叉搜索树 是 一种 树结构", summary="二叉搜索树", embedding=emb.embed_query("二叉搜索树"),
        )
    ]
    local.save_session(session)
    local.save_ingest_artifact(
        IngestArtifact(session_id=session.session_id, source_id=uuid.uuid4(), source_kind=SourceKind.pdf, chunks=chunks)
    )
    candidates = GraphExtractionResult(
        concepts=[ExtractedConcept(name="二叉搜索树", canonical_name="二叉搜索树", definition="用于查找的树结构")]
    )
    local.save_graph_artifact(build_graph_artifact(session.session_id, chunks, candidates, embeddings=emb))
    return session.session_id


def test_get_notes_and_test_missing_are_404():
    assert client.get(f"/notes/{uuid.uuid4()}").status_code == 404
    assert client.get(f"/test/{uuid.uuid4()}").status_code == 404


def test_generate_without_llm_binding_is_400():
    session_id = _seed_graph()  # graph exists but no Purpose bound → LLMConfigError → 400
    assert client.post("/generate_notes", json={"session_id": str(session_id)}).status_code == 400
    assert client.post(
        "/generate_test", json={"session_id": str(session_id), "question_count": 4}
    ).status_code == 400


def test_export_note_roundtrips_through_api():
    session_id = uuid.uuid4()
    local.save_note(
        NoteDocument(
            session_id=session_id, title="树笔记", topic="树", summary="总览",
            sections=[NoteSection(title="二叉搜索树", content_md="- 高效查找")],
        )
    )
    res = client.get(f"/export/{session_id}/markdown")
    assert res.status_code == 200
    assert "# 树笔记" in res.text
    assert res.headers["content-type"].startswith("text/markdown")
    # unknown format rejected
    assert client.get(f"/export/{session_id}/docx").status_code == 400


def test_export_test_and_chat_through_api():
    session_id = uuid.uuid4()
    local.save_session(CourseSession(session_id=session_id, course_title="c", lecture_title="l"))
    local.save_test(
        DocumentModel(
            session_id=session_id, title="树水平测试", summary="s",
            questions=[QuestionModel(
                question_type="single_choice", stem="Q?",
                choices=[ChoiceModel(choice_id="A", text="x")], answer="A", explanation="e",
            )],
        )
    )
    local.save_chat(
        ChatDocument(session_id=session_id, messages=[ChatMessage(role="user", content="hi")])
    )
    test_res = client.get(f"/export/{session_id}/test/markdown")
    assert test_res.status_code == 200 and "树水平测试" in test_res.text
    assert client.get(f"/export/{session_id}/exam/markdown").status_code == 200
    chat_res = client.get(f"/export/{session_id}/chat/markdown")
    assert chat_res.status_code == 200 and "对话记录" in chat_res.text


def test_notes_attach_stream_idle_then_replays_saved_note():
    session_id = uuid.uuid4()
    idle = client.get(f"/notes/{session_id}/stream")  # no job, no note → idle
    assert idle.status_code == 200 and '"idle"' in idle.text

    local.save_note(
        NoteDocument(
            session_id=session_id, title="流式笔记", topic="x", summary="s",
            sections=[NoteSection(title="S", content_md="- a")],
        )
    )
    done = client.get(f"/notes/{session_id}/stream")  # note exists → replayed as done
    assert done.status_code == 200 and '"done"' in done.text and "流式笔记" in done.text


def test_test_attach_stream_idle_then_replays_saved_test():
    session_id = uuid.uuid4()
    idle = client.get(f"/test/{session_id}/stream")
    assert idle.status_code == 200 and '"idle"' in idle.text

    local.save_test(
        DocumentModel(
            session_id=session_id, title="流式测试", summary="s",
            questions=[QuestionModel(
                question_type="single_choice", stem="Q?",
                choices=[ChoiceModel(choice_id="A", text="x")], answer="A", explanation="e",
            )],
        )
    )
    done = client.get(f"/test/{session_id}/stream")
    assert done.status_code == 200 and '"done"' in done.text and "流式测试" in done.text
    assert '"test"' in done.text
    assert client.get(f"/exam/{session_id}").status_code == 200


def test_load_test_migrates_legacy_exam_artifact():
    session_id = uuid.uuid4()
    local.write_text_atomic(
        local.exam_path(session_id),
        """{
          "exam_id": "legacy-id",
          "session_id": "%s",
          "title": "旧测验",
          "summary": "",
          "questions": []
        }""" % session_id,
    )

    loaded = local.load_test(session_id)

    assert loaded.test_id == "legacy-id"
    assert loaded.exam_id == "legacy-id"
