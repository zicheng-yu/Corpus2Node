from __future__ import annotations

import json
import os
import shutil
import uuid
from pathlib import Path
from typing import TypeVar

from pydantic import BaseModel

from corpus2node.config import settings
from corpus2node.core.types import (
    ChatDocument,
    CourseSession,
    DiscoveryReport,
    GraphArtifact,
    IngestArtifact,
    NoteDocument,
    TestDocument,
)

T = TypeVar("T", bound=BaseModel)


def _root() -> Path:
    path = Path(settings.local_storage_path)
    path.mkdir(parents=True, exist_ok=True)
    return path


def session_dir(session_id: uuid.UUID) -> Path:
    path = _root() / str(session_id)
    path.mkdir(parents=True, exist_ok=True)
    return path


def list_session_ids() -> list[uuid.UUID]:
    ids: list[uuid.UUID] = []
    for candidate in _root().iterdir():
        if not candidate.is_dir():
            continue
        try:
            ids.append(uuid.UUID(candidate.name))
        except ValueError:
            continue
    return sorted(ids, reverse=True)


def _read_model(path: Path, model_type: type[T]) -> T:
    return model_type.model_validate_json(path.read_text(encoding="utf-8"))


def write_text_atomic(path: Path, text: str) -> Path:
    """Write text via same-directory replace so readers never see partial JSON."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)
    return path


def write_bytes_atomic(path: Path, data: bytes) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    tmp.write_bytes(data)
    os.replace(tmp, path)
    return path


def _write_model(path: Path, model: BaseModel) -> Path:
    return write_text_atomic(path, model.model_dump_json(indent=2))


def session_path(session_id: uuid.UUID) -> Path:
    return session_dir(session_id) / "session.json"


def save_session(session: CourseSession) -> Path:
    return _write_model(session_path(session.session_id), session)


def load_session(session_id: uuid.UUID) -> CourseSession:
    return _read_model(session_path(session_id), CourseSession)


def delete_session(session_id: uuid.UUID) -> None:
    dir_path = _root() / str(session_id)
    if dir_path.exists():
        shutil.rmtree(dir_path)


COURSE_GRAPH_LECTURE_PREFIX = "[总图谱] "


def list_sessions_by_course(course_title: str) -> list[CourseSession]:
    """Return all sessions whose course_title matches, excluding virtual course-graph sessions."""
    sessions: list[CourseSession] = []
    for session_id in list_session_ids():
        try:
            session = load_session(session_id)
        except (FileNotFoundError, Exception):
            continue
        if session.course_title == course_title and not session.lecture_title.startswith(COURSE_GRAPH_LECTURE_PREFIX):
            sessions.append(session)
    return sessions


def find_course_session(course_title: str) -> CourseSession | None:
    """Find the virtual session that stores the course-level graph, if it exists."""
    target_lecture = f"{COURSE_GRAPH_LECTURE_PREFIX}{course_title}"
    for session_id in list_session_ids():
        try:
            session = load_session(session_id)
        except (FileNotFoundError, Exception):
            continue
        if session.course_title == course_title and session.lecture_title == target_lecture:
            return session
    return None


def upload_dir(session_id: uuid.UUID) -> Path:
    path = session_dir(session_id) / "uploads"
    path.mkdir(parents=True, exist_ok=True)
    return path


def safe_display_filename(filename: str) -> str:
    return Path(filename or "upload").name or "upload"


def stored_upload_filename(source_id: uuid.UUID, filename: str) -> str:
    return f"{source_id}{Path(safe_display_filename(filename)).suffix.lower()}"


def write_upload(session_id: uuid.UUID, filename: str, data: bytes, *, source_id: uuid.UUID | None = None) -> Path:
    safe_name = stored_upload_filename(source_id, filename) if source_id else safe_display_filename(filename)
    path = upload_dir(session_id) / safe_name
    return write_bytes_atomic(path, data)


def ingest_dir(session_id: uuid.UUID) -> Path:
    path = session_dir(session_id) / "ingest"
    path.mkdir(parents=True, exist_ok=True)
    return path


def ingest_path(session_id: uuid.UUID, source_id: uuid.UUID) -> Path:
    return ingest_dir(session_id) / f"{source_id}.json"


def save_ingest_artifact(artifact: IngestArtifact) -> Path:
    return _write_model(ingest_path(artifact.session_id, artifact.source_id), artifact)


def load_ingest_artifact(session_id: uuid.UUID, source_id: uuid.UUID) -> IngestArtifact:
    return _read_model(ingest_path(session_id, source_id), IngestArtifact)


def list_ingest_artifacts(session_id: uuid.UUID) -> list[IngestArtifact]:
    path = ingest_dir(session_id)
    return [
        _read_model(candidate, IngestArtifact)
        for candidate in sorted(path.glob("*.json"))
    ]


def graph_path(session_id: uuid.UUID) -> Path:
    return session_dir(session_id) / "graph.json"


def save_graph_artifact(graph: GraphArtifact) -> Path:
    return _write_model(graph_path(graph.session_id), graph)


def load_graph_artifact(session_id: uuid.UUID) -> GraphArtifact:
    return _read_model(graph_path(session_id), GraphArtifact)


def delete_graph_artifact(session_id: uuid.UUID) -> None:
    graph_path(session_id).unlink(missing_ok=True)


def notes_path(session_id: uuid.UUID) -> Path:
    return session_dir(session_id) / "notes.json"


def save_note(note: NoteDocument) -> Path:
    return _write_model(notes_path(note.session_id), note)


def load_note(session_id: uuid.UUID) -> NoteDocument:
    return _read_model(notes_path(session_id), NoteDocument)


def delete_note(session_id: uuid.UUID) -> None:
    notes_path(session_id).unlink(missing_ok=True)


def exam_path(session_id: uuid.UUID) -> Path:
    return session_dir(session_id) / "exam.json"


def test_path(session_id: uuid.UUID) -> Path:
    return session_dir(session_id) / "test.json"


def save_test(test: TestDocument) -> Path:
    return _write_model(test_path(test.session_id), test)


def load_test(session_id: uuid.UUID) -> TestDocument:
    path = test_path(session_id)
    if not path.exists():
        path = exam_path(session_id)
    return _read_model(path, TestDocument)


def delete_test(session_id: uuid.UUID) -> None:
    test_path(session_id).unlink(missing_ok=True)
    exam_path(session_id).unlink(missing_ok=True)


# Compatibility wrappers for older callers and exam.json artifacts.
def save_exam(exam: TestDocument) -> Path:
    return save_test(exam)


def load_exam(session_id: uuid.UUID) -> TestDocument:
    return load_test(session_id)


def delete_exam(session_id: uuid.UUID) -> None:
    delete_test(session_id)


def chat_path(session_id: uuid.UUID) -> Path:
    return session_dir(session_id) / "chat.json"


def save_chat(chat: ChatDocument) -> Path:
    return _write_model(chat_path(chat.session_id), chat)


def load_chat(session_id: uuid.UUID) -> ChatDocument:
    return _read_model(chat_path(session_id), ChatDocument)


def delete_chat(session_id: uuid.UUID) -> None:
    chat_path(session_id).unlink(missing_ok=True)


def discovery_dir() -> Path:
    path = _root() / "discoveries"
    path.mkdir(parents=True, exist_ok=True)
    return path


def discovery_path(discovery_id: str) -> Path:
    return discovery_dir() / f"{discovery_id}.json"


def save_discovery_report(report: DiscoveryReport) -> Path:
    return _write_model(discovery_path(report.discovery_id), report)


def load_discovery_report(discovery_id: str) -> DiscoveryReport:
    return _read_model(discovery_path(discovery_id), DiscoveryReport)


def delete_discovery_report(discovery_id: str) -> None:
    discovery_path(discovery_id).unlink(missing_ok=True)


def list_discovery_reports() -> list[DiscoveryReport]:
    reports = [_read_model(candidate, DiscoveryReport) for candidate in discovery_dir().glob("*.json")]
    return sorted(reports, key=lambda report: report.generated_at, reverse=True)


def write_json(path: Path, data: dict) -> Path:
    return write_text_atomic(path, json.dumps(data, ensure_ascii=False, indent=2))
