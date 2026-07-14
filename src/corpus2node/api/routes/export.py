from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import PlainTextResponse
from sqlalchemy.ext.asyncio import AsyncSession

from corpus2node.accounts.database import get_db
from corpus2node.accounts.dependencies import optional_principal, require_resource_access
from corpus2node.accounts.schemas import Principal
from corpus2node.export.renderer import SUPPORTED_FORMATS, get_renderer, render_chat_markdown
from corpus2node.storage import local

router = APIRouter(prefix="/export", tags=["export"])

_MEDIA_TYPE = {"markdown": "text/markdown", "txt": "text/plain", "tex": "application/x-tex"}


def _owner_key(principal: Principal | None) -> str | None:
    if principal is None or principal.organization_id is None:
        return None
    return f"{principal.organization_id}/{principal.user_id}"


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


@router.get("/{session_id}/test/{fmt}")
@router.get("/{session_id}/exam/{fmt}", include_in_schema=False)
async def export_test(
    session_id: UUID,
    fmt: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    principal = optional_principal(request)
    await require_resource_access(request, db, "session", str(session_id))
    try:
        test = local.load_test(session_id, _owner_key(principal))
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="No generated test for this session.") from exc
    return _render(test.model_dump(), fmt, filename=f"test_{session_id}")


@router.get("/{session_id}/chat/markdown")
async def export_chat(
    session_id: UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    principal = optional_principal(request)
    await require_resource_access(request, db, "session", str(session_id))
    try:
        session = local.load_session(session_id)
        chat = local.load_chat(session_id, _owner_key(principal))
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Session or chat not found.") from exc
    content = render_chat_markdown(chat, title=f"{session.lecture_title} - 对话记录")
    return PlainTextResponse(content, media_type="text/markdown")


@router.get("/{session_id}/{fmt}")
async def export_note(
    session_id: UUID,
    fmt: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    principal = optional_principal(request)
    await require_resource_access(request, db, "session", str(session_id))
    try:
        note = local.load_note(session_id, _owner_key(principal))
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="No generated notes for this session.") from exc
    return _render(note.model_dump(), fmt, filename=f"notes_{session_id}")
