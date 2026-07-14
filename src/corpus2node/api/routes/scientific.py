from __future__ import annotations

import asyncio
import hashlib
import json
from pathlib import Path
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from corpus2node import jobs
from corpus2node.accounts.database import get_db, session_factory
from corpus2node.accounts.dependencies import optional_principal, require_resource_access
from corpus2node.accounts.entitlements import resolve_entitlements
from corpus2node.accounts.models import Resource
from corpus2node.accounts.schemas import Principal
from corpus2node.accounts.service import (
    AuthorizationError,
    QuotaError,
    add_activity,
    enforce_quota,
    organization_for_principal,
    record_usage,
    register_resource,
    require_role,
)
from corpus2node.config import settings
from corpus2node.scientific.engine import ScientificInputError, run_scientific_analysis
from corpus2node.scientific.parsers import ScientificParseError, parse_grobid_pdf, parse_scientific_xml
from corpus2node.scientific.schemas import (
    ScientificAnalysisRequest,
    ScientificDocument,
    ScientificParseRequest,
    ScientificReport,
)
from corpus2node.storage import local

router = APIRouter(prefix="/scientific", tags=["scientific"])


async def _preflight(
    request: Request, db: AsyncSession, session_ids: list[UUID], *, generative: bool
) -> tuple[Principal | None, str | None]:
    principal = optional_principal(request)
    project_ids: set[str] = set()
    for session_id in session_ids:
        resource = await require_resource_access(request, db, "session", str(session_id))
        if resource and resource.project_id:
            project_ids.add(resource.project_id)
    if principal is not None and generative:
        try:
            require_role(principal, "member")
            await enforce_quota(db, principal, "ai_task")
            organization = await organization_for_principal(db, principal)
        except AuthorizationError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        except QuotaError as exc:
            raise HTTPException(status_code=429, detail=exc.detail()) from exc
        limit = int(resolve_entitlements(organization)["max_scientific_papers"])
        if len(session_ids) > limit:
            raise HTTPException(
                status_code=429,
                detail={
                    "code": "quota_exceeded",
                    "metric": "scientific_papers",
                    "used": len(session_ids),
                    "limit": limit,
                    "reset_at": None,
                },
            )
    return principal, next(iter(project_ids)) if len(project_ids) == 1 else None


async def _record_report(principal: Principal, report: ScientificReport, project_id: str | None) -> None:
    async with session_factory()() as db:
        await register_resource(
            db,
            principal=principal,
            resource_type="scientific_report",
            resource_key=report.report_id,
            project_id=project_id,
            owner_user_id=None,
            artifact_path=str(local.scientific_path(report.report_id)),
        )
        await add_activity(
            db,
            principal,
            "scientific_report.generated",
            project_id=project_id,
            resource_type="scientific_report",
            resource_key=report.report_id,
            detail={"papers": len(report.papers), "claims": len(report.claims)},
        )
        await record_usage(
            db,
            principal,
            idempotency_key=f"scientific:{report.report_id}",
            metric="ai_task",
            purpose="scientific",
            detail={
                "papers": len(report.papers),
                "input_chars": sum(
                    len(chunk.text)
                    for session_id in report.session_ids
                    for artifact in local.list_ingest_artifacts(session_id)
                    for chunk in artifact.chunks
                ),
                "output_chars": len(report.model_dump_json()),
            },
        )
        await db.commit()


@router.post("/run")
async def run_scientific_route(
    payload: ScientificAnalysisRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> ScientificReport:
    principal, project_id = await _preflight(request, db, payload.session_ids, generative=True)
    try:
        report = await run_scientific_analysis(payload)
    except ScientificInputError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if principal is not None:
        await _record_report(principal, report, project_id)
    return report


@router.post("/run/stream")
async def run_scientific_stream(
    payload: ScientificAnalysisRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> StreamingResponse:
    principal, project_id = await _preflight(request, db, payload.session_ids, generative=True)
    fingerprint = _request_fingerprint(payload)

    async def runner(emit: jobs.Emit) -> None:
        emit({"type": "start", "data": {"job_id": fingerprint}})
        report = await run_scientific_analysis(payload)
        if principal is not None:
            await _record_report(principal, report, project_id)
        emit({"type": "done", "data": {"report": report.model_dump(mode="json")}})

    try:
        org = principal.organization_id if principal is not None else "legacy"
        job = jobs.start(f"scientific:{org}:{fingerprint}", runner, fingerprint=fingerprint)
    except jobs.JobConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    async def events():
        async for event in job.subscribe():
            yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"

    return StreamingResponse(events(), media_type="text/event-stream")


@router.post("/parse")
async def parse_scientific_sources(
    payload: ScientificParseRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> list[ScientificDocument]:
    await _preflight(request, db, [payload.session_id], generative=True)
    try:
        session = local.load_session(payload.session_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="资料集不存在。") from exc
    requested = {str(value) for value in payload.source_ids}
    sources = [value for value in session.source_files if not requested or str(value.source_id) in requested]
    if not sources:
        raise HTTPException(status_code=400, detail="没有可解析的指定文献。")
    documents: list[ScientificDocument] = []
    try:
        for source in sources:
            suffix = Path(source.filename).suffix.lower()
            if suffix in {".xml", ".nxml"}:
                document = await asyncio.to_thread(
                    parse_scientific_xml, source.storage_path, source_id=str(source.source_id)
                )
            elif suffix == ".pdf":
                document = await asyncio.to_thread(
                    parse_grobid_pdf,
                    source.storage_path,
                    source_id=str(source.source_id),
                    base_url=settings.grobid_base_url,
                )
            else:
                continue
            local.save_scientific_document(payload.session_id, document)
            documents.append(document)
    except ScientificParseError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    if not documents:
        raise HTTPException(status_code=400, detail="仅支持 JATS/XML、TEI/XML 或 PDF 科研结构解析。")
    return documents


@router.get("/documents/{session_id}")
async def list_scientific_documents(
    session_id: UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> list[ScientificDocument]:
    await _preflight(request, db, [session_id], generative=False)
    try:
        local.load_session(session_id)
        return local.list_scientific_documents(session_id)
    except (FileNotFoundError, ValueError) as exc:
        raise HTTPException(status_code=404, detail="资料集不存在。") from exc


@router.get("")
async def list_scientific_reports(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> list[ScientificReport]:
    principal = optional_principal(request)
    if principal is None:
        return local.list_scientific_reports()
    keys = (
        await db.scalars(
            select(Resource.resource_key).where(
                Resource.organization_id == principal.organization_id,
                Resource.resource_type == "scientific_report",
                Resource.status == "active",
            )
        )
    ).all()
    return sorted(
        [local.load_scientific_report(value) for value in keys],
        key=lambda value: value.generated_at,
        reverse=True,
    )


@router.get("/{report_id}")
async def get_scientific_report(
    report_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> ScientificReport:
    await require_resource_access(request, db, "scientific_report", report_id)
    try:
        return local.load_scientific_report(report_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="科研证据报告不存在。") from exc


@router.delete("/{report_id}")
async def delete_scientific_report(
    report_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict[str, bool]:
    principal = optional_principal(request)
    resource = await require_resource_access(request, db, "scientific_report", report_id)
    try:
        local.load_scientific_report(report_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="科研证据报告不存在。") from exc
    if principal is None:
        local.delete_scientific_report(report_id)
    else:
        try:
            require_role(principal, "admin")
        except AuthorizationError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        assert resource is not None
        resource.status = "archived"
        await db.commit()
    return {"ok": True}


def _request_fingerprint(request: ScientificAnalysisRequest) -> str:
    payload = request.model_dump(mode="json")
    return hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
