from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, HTTPException, Response
from fastapi.responses import PlainTextResponse

from corpus2node.export.renderer import SUPPORTED_FORMATS, get_renderer, render_chat_markdown
from corpus2node.storage import local

router = APIRouter(prefix="/export", tags=["export"])

_MEDIA_TYPE = {"markdown": "text/markdown", "txt": "text/plain", "tex": "application/x-tex"}


def _render(document: dict, fmt: str, *, filename: str):
    if fmt not in SUPPORTED_FORMATS:
        raise HTTPException(status_code=400, detail=f"Unknown format: {fmt}")
    try:
        content = get_renderer(fmt).render(document, fmt)
    except RuntimeError as exc:  # PDF engine/deps missing
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if fmt == "pdf":
        return Response(
            content,
            media_type="application/pdf",
            headers={"Content-Disposition": f"attachment; filename={filename}.pdf"},
        )
    return PlainTextResponse(content, media_type=_MEDIA_TYPE[fmt])


@router.get("/{session_id}/exam/{fmt}")
def export_exam(session_id: UUID, fmt: str):
    try:
        exam = local.load_exam(session_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="No generated exam for this session.") from exc
    return _render(exam.model_dump(), fmt, filename=f"exam_{session_id}")


@router.get("/{session_id}/chat/markdown")
def export_chat(session_id: UUID):
    try:
        session = local.load_session(session_id)
        chat = local.load_chat(session_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Session or chat not found.") from exc
    content = render_chat_markdown(chat, title=f"{session.lecture_title} - 对话记录")
    return PlainTextResponse(content, media_type="text/markdown")


@router.get("/{session_id}/{fmt}")
def export_note(session_id: UUID, fmt: str):
    try:
        note = local.load_note(session_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="No generated notes for this session.") from exc
    return _render(note.model_dump(), fmt, filename=f"notes_{session_id}")
