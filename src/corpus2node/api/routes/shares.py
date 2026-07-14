from __future__ import annotations

import json
from datetime import timedelta
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from corpus2node.accounts.database import get_db
from corpus2node.accounts.dependencies import current_principal
from corpus2node.accounts.entitlements import resolve_entitlements
from corpus2node.accounts.models import Project, ProjectRevision, Resource, ShareLink
from corpus2node.accounts.schemas import Principal, ShareLinkView, ShareSnapshot
from corpus2node.accounts.security import hash_token, random_token
from corpus2node.accounts.service import (
    AuthorizationError,
    active_share_count,
    add_activity,
    ensure_writable,
    register_resource,
    require_role,
    resource_for_principal,
)
from corpus2node.config import settings
from corpus2node.core.clock import utcnow
from corpus2node.core.types import DiscoveryReport, GraphArtifact, GraphArtifactView
from corpus2node.scientific.schemas import ScientificReport
from corpus2node.storage import local

router = APIRouter(tags=["shares"])
_SHAREABLE_TYPES = {"project_revision", "scientific_report", "discovery_report"}


class ShareCreate(BaseModel):
    resource_type: str
    resource_key: str = Field(min_length=1, max_length=160)
    expires_in_days: int = Field(default=7, ge=1, le=365)


class ShareResolve(BaseModel):
    token: str = Field(min_length=32, max_length=256)


def _share_url(raw_token: str) -> str:
    return f"{settings.public_app_url.rstrip('/')}/share#token={raw_token}"


def _view(value: ShareLink, *, raw_token: str | None = None) -> ShareLinkView:
    return ShareLinkView(
        share_id=value.share_id,
        resource_type=value.resource_type,
        resource_key=value.resource_key,
        expires_at=value.expires_at,
        revoked_at=value.revoked_at,
        share_url=_share_url(raw_token) if raw_token else None,
    )


@router.post("/shares", response_model=ShareLinkView)
async def create_share(
    payload: ShareCreate,
    principal: Principal = Depends(current_principal),
    db: AsyncSession = Depends(get_db),
) -> ShareLinkView:
    try:
        require_role(principal, "admin")
        organization = await ensure_writable(db, principal)
    except AuthorizationError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    if payload.resource_type not in _SHAREABLE_TYPES:
        raise HTTPException(status_code=400, detail="Resource type cannot be shared.")
    target = await resource_for_principal(db, principal, payload.resource_type, payload.resource_key)
    if target is None:
        raise HTTPException(status_code=404, detail="Resource not found.")
    entitlements = resolve_entitlements(organization)
    used = await active_share_count(db, organization.organization_id)
    limit = int(entitlements["max_active_shares"])
    if used >= limit:
        raise HTTPException(
            status_code=429,
            detail={
                "code": "quota_exceeded",
                "metric": "active_shares",
                "used": used,
                "limit": limit,
                "reset_at": None,
            },
        )
    max_days = int(entitlements["max_share_days"])
    if payload.expires_in_days > max_days:
        raise HTTPException(
            status_code=429,
            detail={
                "code": "quota_exceeded",
                "metric": "share_days",
                "used": payload.expires_in_days,
                "limit": max_days,
                "reset_at": None,
            },
        )
    raw_token = random_token()
    share = ShareLink(
        organization_id=organization.organization_id,
        resource_type=payload.resource_type,
        resource_key=payload.resource_key,
        token_hash=hash_token(raw_token),
        created_by_user_id=principal.user_id,
        expires_at=utcnow() + timedelta(days=payload.expires_in_days),
    )
    db.add(share)
    await db.flush()
    try:
        title, snapshot = await _snapshot(db, target)
    except (FileNotFoundError, ValueError):
        raise HTTPException(status_code=404, detail="Resource not found.") from None
    snapshot_document = json.dumps(
        {"title": title, "payload": snapshot}, ensure_ascii=False, indent=2
    )
    snapshot_bytes = len(snapshot_document.encode("utf-8"))
    storage_used = int(
        await db.scalar(
            select(func.coalesce(func.sum(Resource.size_bytes), 0)).where(
                Resource.organization_id == organization.organization_id,
                Resource.status == "active",
            )
        )
        or 0
    )
    storage_limit = int(entitlements["max_storage_bytes"])
    if storage_used + snapshot_bytes > storage_limit:
        raise HTTPException(
            status_code=429,
            detail={
                "code": "quota_exceeded",
                "metric": "storage_bytes",
                "used": storage_used,
                "limit": storage_limit,
                "reset_at": None,
            },
        )
    snapshot_path = _save_share_snapshot(share.share_id, snapshot_document)
    share.snapshot_path = str(snapshot_path)
    share.snapshot_title = title
    await register_resource(
        db,
        principal=principal,
        resource_type="share_snapshot",
        resource_key=share.share_id,
        project_id=target.project_id,
        artifact_path=str(snapshot_path),
    )
    await add_activity(
        db,
        principal,
        "share.created",
        project_id=target.project_id,
        resource_type=payload.resource_type,
        resource_key=payload.resource_key,
        detail={"share_id": share.share_id, "expires_at": share.expires_at.isoformat()},
    )
    await db.commit()
    return _view(share, raw_token=raw_token)


@router.get("/shares", response_model=list[ShareLinkView])
async def list_shares(
    principal: Principal = Depends(current_principal),
    db: AsyncSession = Depends(get_db),
) -> list[ShareLinkView]:
    try:
        require_role(principal, "admin")
    except AuthorizationError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    if principal.organization_id is None:
        return []
    values = (
        await db.scalars(
            select(ShareLink)
            .where(ShareLink.organization_id == principal.organization_id)
            .order_by(ShareLink.created_at.desc())
        )
    ).all()
    return [_view(value) for value in values]


@router.delete("/shares/{share_id}")
async def revoke_share(
    share_id: str,
    principal: Principal = Depends(current_principal),
    db: AsyncSession = Depends(get_db),
) -> dict[str, bool]:
    try:
        require_role(principal, "admin")
    except AuthorizationError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    share = await db.get(ShareLink, share_id)
    if share is None or share.organization_id != principal.organization_id:
        raise HTTPException(status_code=404, detail="Share link not found.")
    if share.revoked_at is None:
        share.revoked_at = utcnow()
        snapshot_resource = await db.scalar(
            select(Resource).where(
                Resource.organization_id == principal.organization_id,
                Resource.resource_type == "share_snapshot",
                Resource.resource_key == share.share_id,
            )
        )
        if snapshot_resource is not None:
            snapshot_resource.status = "archived"
        await add_activity(
            db,
            principal,
            "share.revoked",
            resource_type=share.resource_type,
            resource_key=share.resource_key,
            detail={"share_id": share.share_id},
        )
        await db.commit()
    return {"ok": True}


@router.post("/public/shares/resolve", response_model=ShareSnapshot)
async def resolve_share(payload: ShareResolve, db: AsyncSession = Depends(get_db)) -> ShareSnapshot:
    share = await db.scalar(select(ShareLink).where(ShareLink.token_hash == hash_token(payload.token)))
    if share is None or share.revoked_at is not None or share.expires_at <= utcnow():
        raise HTTPException(status_code=404, detail="Share link not found.")
    resource = await db.scalar(
        select(Resource).where(
            Resource.organization_id == share.organization_id,
            Resource.resource_type == share.resource_type,
            Resource.resource_key == share.resource_key,
            Resource.status == "active",
        )
    )
    if resource is None:
        raise HTTPException(status_code=404, detail="Share link not found.")
    try:
        await _ensure_target_active(db, resource)
        saved = json.loads(Path(share.snapshot_path).read_text(encoding="utf-8"))
        title = str(saved["title"])
        snapshot = dict(saved["payload"])
    except (FileNotFoundError, OSError, KeyError, TypeError, ValueError, json.JSONDecodeError):
        raise HTTPException(status_code=404, detail="Share link not found.") from None
    return ShareSnapshot(
        resource_type=share.resource_type,
        title=title,
        payload=snapshot,
        expires_at=share.expires_at,
    )


async def _snapshot(db: AsyncSession, resource: Resource) -> tuple[str, dict]:
    if resource.resource_type == "project_revision":
        revision = await db.get(ProjectRevision, resource.resource_key)
        project = await db.get(Project, resource.project_id) if resource.project_id else None
        if revision is None or revision.status != "ready" or project is None or project.archived_at is not None:
            raise FileNotFoundError
        graph = GraphArtifact.model_validate_json(Path(resource.artifact_path).read_text(encoding="utf-8"))
        return (
            f"{project.name} - 修订版 {revision.revision_number}",
            {
                "revision": {
                    "revision_id": revision.revision_id,
                    "revision_number": revision.revision_number,
                    "summary": revision.summary,
                    "completed_at": revision.completed_at.isoformat() if revision.completed_at else None,
                },
                "graph": GraphArtifactView.from_artifact(graph).model_dump(mode="json"),
            },
        )
    if resource.resource_type == "scientific_report":
        report = ScientificReport.model_validate_json(Path(resource.artifact_path).read_text(encoding="utf-8"))
        return report.title_zh, _public_scientific_report(report)
    if resource.resource_type == "discovery_report":
        report = DiscoveryReport.model_validate_json(Path(resource.artifact_path).read_text(encoding="utf-8"))
        return report.title or "知识发现报告", _public_discovery_report(report)
    raise FileNotFoundError


async def _ensure_target_active(db: AsyncSession, resource: Resource) -> None:
    if resource.project_id:
        project = await db.get(Project, resource.project_id)
        if project is None or project.archived_at is not None:
            raise FileNotFoundError
    if resource.resource_type == "project_revision":
        revision = await db.get(ProjectRevision, resource.resource_key)
        if revision is None or revision.status != "ready":
            raise FileNotFoundError


def _save_share_snapshot(share_id: str, document: str) -> Path:
    path = Path(settings.local_storage_path) / "shares" / f"{share_id}.json"
    local.write_text_atomic(path, document)
    return path


def _public_scientific_report(report: ScientificReport) -> dict:
    """Whitelist the report fields needed by the read-only public renderer."""
    return {
        "objective_zh": report.objective_zh,
        "generated_at": report.generated_at.isoformat(),
        "papers": [
            {
                "source_title": value.source_title,
                "title_zh": value.title_zh,
                "title_original": value.title_original,
                "research_problem_zh": value.research_problem_zh,
                "method_summary_zh": value.method_summary_zh,
                "result_summary_zh": value.result_summary_zh,
                "limitations_zh": value.limitations_zh,
            }
            for value in report.papers
        ],
        "claims": [
            value.model_dump(
                mode="json",
                include={
                    "claim_id",
                    "claim_type",
                    "statement_zh",
                    "statement_original",
                    "evidence_quote",
                    "subject",
                    "predicate_zh",
                    "object",
                    "polarity",
                    "modality",
                    "confidence",
                    "evidence_ids",
                },
            )
            for value in report.claims
        ],
        "evidence": [
            {
                "evidence_id": value.evidence_id,
                "locator": value.locator,
                "snippet": value.snippet,
            }
            for value in report.evidence
        ],
        "evidence_matrix": [
            value.model_dump(mode="json", exclude={"session_id"}) for value in report.evidence_matrix
        ],
        "insights": [
            value.model_dump(mode="json", exclude={"related_session_ids"}) for value in report.insights
        ],
        "decision_cards": [value.model_dump(mode="json") for value in report.decision_cards],
    }


def _public_discovery_report(report: DiscoveryReport) -> dict:
    """Expose conclusions and evidence excerpts without internal graph identifiers."""

    def participant(value) -> dict:
        return {
            "course_title": value.course_title,
            "lecture_title": value.lecture_title,
            "concept_name": value.concept_name,
            "summary": value.summary,
        }

    def evidence(value) -> dict:
        return {
            "course_title": value.course_title,
            "lecture_title": value.lecture_title,
            "concept_name": value.concept_name,
            "locator": value.locator,
            "snippet": value.snippet,
        }

    return {
        "intent": report.intent,
        "generated_at": report.generated_at.isoformat(),
        "findings": [
            {
                "finding_id": value.finding_id,
                "title": value.title,
                "summary": value.summary,
                "relation_type": value.relation_type,
                "confidence": value.confidence,
                "novelty": value.novelty,
                "participants": [participant(item) for item in value.participants],
                "evidence": [evidence(item) for item in value.evidence],
                "reasoning": value.reasoning,
            }
            for value in report.findings
        ],
        "proposals": [
            {
                "proposal_id": value.proposal_id,
                "title": value.title,
                "pitch": value.pitch,
                "combination": value.combination,
                "first_step": value.first_step,
                "risks": value.risks,
                "deep_dive": value.deep_dive,
                "confidence": value.confidence,
                "sources": [participant(item) for item in value.sources],
                "evidence": [evidence(item) for item in value.evidence],
            }
            for value in report.proposals
        ],
    }
