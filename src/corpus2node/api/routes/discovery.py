from __future__ import annotations

import hashlib
import json
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from corpus2node import jobs
from corpus2node.accounts.database import get_db, session_factory
from corpus2node.accounts.dependencies import optional_principal, require_resource_access
from corpus2node.accounts.models import Resource
from corpus2node.accounts.schemas import Principal
from corpus2node.accounts.service import (
    AuthorizationError,
    QuotaError,
    add_activity,
    enforce_quota,
    ensure_writable,
    record_usage,
    register_resource,
    require_role,
)
from corpus2node.core.concurrency import keyed_lock
from corpus2node.core.types import DiscoveryMode, DiscoveryReport, DiscoveryRequest
from corpus2node.discovery import DiscoveryInputError, deepen_proposal, make_deepener_or_none, run_discovery
from corpus2node.storage import local

router = APIRouter(prefix="/discovery", tags=["discovery"])


async def _scoped_request(
    payload: DiscoveryRequest,
    request: Request,
    db: AsyncSession,
) -> tuple[DiscoveryRequest, Principal | None]:
    principal = optional_principal(request)
    if principal is None:
        return payload, None
    try:
        require_role(principal, "member")
        await enforce_quota(db, principal, "ai_task")
    except AuthorizationError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except QuotaError as exc:
        raise HTTPException(status_code=429, detail=exc.detail()) from exc
    if payload.session_ids:
        for session_id in payload.session_ids:
            await require_resource_access(request, db, "session", str(session_id))
        return payload, principal
    keys = (
        await db.scalars(
            select(Resource.resource_key).where(
                Resource.organization_id == principal.organization_id,
                Resource.resource_type == "session",
                Resource.status == "active",
            )
        )
    ).all()
    return payload.model_copy(update={"session_ids": [UUID(value) for value in keys], "mode": DiscoveryMode.selected}), principal


async def _record_report(principal: Principal, report: DiscoveryReport) -> None:
    async with session_factory()() as db:
        await register_resource(
            db,
            principal=principal,
            resource_type="discovery_report",
            resource_key=report.discovery_id,
            artifact_path=str(local.discovery_path(report.discovery_id)),
        )
        await add_activity(
            db,
            principal,
            "discovery_report.generated",
            resource_type="discovery_report",
            resource_key=report.discovery_id,
            detail={"sessions": len(report.session_ids), "proposals": len(report.proposals)},
        )
        await record_usage(
            db,
            principal,
            idempotency_key=f"discovery:{report.discovery_id}",
            metric="ai_task",
            purpose="discovery",
            detail={
                "sessions": len(report.session_ids),
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


async def _history_reports(principal: Principal | None, db: AsyncSession) -> list[DiscoveryReport] | None:
    if principal is None:
        return None
    keys = (
        await db.scalars(
            select(Resource.resource_key).where(
                Resource.organization_id == principal.organization_id,
                Resource.resource_type == "discovery_report",
                Resource.status == "active",
            )
        )
    ).all()
    reports: list[DiscoveryReport] = []
    for key in keys:
        try:
            reports.append(local.load_discovery_report(key))
        except FileNotFoundError:
            continue
    return reports


@router.post("/run")
async def run_discovery_route(
    payload: DiscoveryRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> DiscoveryReport:
    payload, principal = await _scoped_request(payload, request, db)
    history_reports = await _history_reports(principal, db)
    try:
        report = await run_discovery(payload, history_reports=history_reports)
    except DiscoveryInputError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    local.save_discovery_report(report)
    if principal is not None:
        await _record_report(principal, report)
    return report


@router.post("/run/stream")
async def run_discovery_stream(
    payload: DiscoveryRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> StreamingResponse:
    payload, principal = await _scoped_request(payload, request, db)
    history_reports = await _history_reports(principal, db)
    fingerprint = hashlib.sha256(
        json.dumps(payload.model_dump(mode="json"), sort_keys=True, ensure_ascii=False).encode()
    ).hexdigest()

    async def runner(emit: jobs.Emit) -> None:
        emit({"type": "start", "data": {"job_id": fingerprint}})
        report = await run_discovery(payload, history_reports=history_reports)
        local.save_discovery_report(report)
        if principal is not None:
            await _record_report(principal, report)
        emit({"type": "done", "data": {"report": report.model_dump(mode="json")}})

    try:
        org = principal.organization_id if principal is not None else "legacy"
        job = jobs.start(f"discovery:{org}:{fingerprint}", runner, fingerprint=fingerprint)
    except jobs.JobConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    async def events():
        async for event in job.subscribe():
            yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"

    return StreamingResponse(events(), media_type="text/event-stream")


@router.get("")
async def list_discoveries(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> list[DiscoveryReport]:
    principal = optional_principal(request)
    if principal is None:
        return local.list_discovery_reports()
    keys = (
        await db.scalars(
            select(Resource.resource_key).where(
                Resource.organization_id == principal.organization_id,
                Resource.resource_type == "discovery_report",
                Resource.status == "active",
            )
        )
    ).all()
    return sorted([local.load_discovery_report(value) for value in keys], key=lambda value: value.generated_at, reverse=True)


@router.get("/{discovery_id}")
async def get_discovery(
    discovery_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> DiscoveryReport:
    await require_resource_access(request, db, "discovery_report", discovery_id)
    try:
        return local.load_discovery_report(discovery_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Discovery report not found.") from exc


@router.delete("/{discovery_id}")
async def delete_discovery(
    discovery_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict[str, bool]:
    principal = optional_principal(request)
    resource = await require_resource_access(request, db, "discovery_report", discovery_id)
    try:
        local.load_discovery_report(discovery_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Discovery report not found.") from exc
    if principal is None:
        local.delete_discovery_report(discovery_id)
    else:
        try:
            require_role(principal, "admin")
        except AuthorizationError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        assert resource is not None
        resource.status = "archived"
        await db.commit()
    return {"ok": True}


class ProposalStatusUpdate(BaseModel):
    status: Literal["new", "kept", "discarded"]


def _load_report_or_404(discovery_id: str) -> DiscoveryReport:
    try:
        return local.load_discovery_report(discovery_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Discovery report not found.") from exc


@router.patch("/{discovery_id}/proposals/{proposal_id}")
async def update_proposal_status(
    discovery_id: str,
    proposal_id: str,
    payload: ProposalStatusUpdate,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> DiscoveryReport:
    """Persist the boss's verdict on a proposal (kept / discarded / back to new).

    Kept and discarded titles are fed into later runs over the same sets as an
    avoid-list, so reruns explore instead of repeating."""
    await require_resource_access(request, db, "discovery_report", discovery_id)
    principal = optional_principal(request)
    if principal is not None:
        try:
            require_role(principal, "member")
            await ensure_writable(db, principal)
        except AuthorizationError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
    async with keyed_lock(f"discovery-report:{discovery_id}"):
        report = _load_report_or_404(discovery_id)
        proposal = next((p for p in report.proposals if p.proposal_id == proposal_id), None)
        if proposal is None:
            raise HTTPException(status_code=404, detail="Proposal not found in this report.")
        proposal.status = payload.status
        local.save_discovery_report(report)
        return report


@router.post("/{discovery_id}/proposals/{proposal_id}/deepen")
async def deepen_proposal_route(
    discovery_id: str,
    proposal_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> DiscoveryReport:
    """Expand one proposal into a minimal executable plan (goal/approach/data/experiment/metrics)."""
    await require_resource_access(request, db, "discovery_report", discovery_id)
    principal = optional_principal(request)
    if principal is not None:
        try:
            require_role(principal, "member")
            await enforce_quota(db, principal, "ai_task")
        except AuthorizationError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        except QuotaError as exc:
            raise HTTPException(status_code=429, detail=exc.detail()) from exc
    async with keyed_lock(f"discovery-report:{discovery_id}"):
        report = _load_report_or_404(discovery_id)
        if all(p.proposal_id != proposal_id for p in report.proposals):
            raise HTTPException(status_code=404, detail="Proposal not found in this report.")
        deepener = make_deepener_or_none()
        if deepener is None:
            raise HTTPException(status_code=400, detail="深挖需要在「设置 → 模型」绑定 chat 或 critic 用途的模型。")
        try:
            report = await deepen_proposal(report, proposal_id, deepener)
        except (KeyError, ValueError) as exc:
            raise HTTPException(status_code=400, detail=f"深挖失败：{exc}") from exc
        local.save_discovery_report(report)
        if principal is not None:
            updated = next(value for value in report.proposals if value.proposal_id == proposal_id)
            await record_usage(
                db,
                principal,
                idempotency_key=f"discovery-deepen:{discovery_id}:{proposal_id}:{hashlib.sha256((updated.deep_dive or '').encode()).hexdigest()}",
                metric="ai_task",
                purpose="discovery",
            )
            await db.commit()
        return report
