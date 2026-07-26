from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, EmailStr
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from corpus2node.accounts.database import get_db
from corpus2node.accounts.dependencies import current_principal
from corpus2node.accounts.entitlements import resolve_entitlements
from corpus2node.accounts.models import Invitation, Membership, Organization, Resource, User
from corpus2node.accounts.schemas import (
    InvitationView,
    MemberView,
    OrganizationView,
    Principal,
    UsageSummary,
)
from corpus2node.accounts.service import (
    AccountError,
    AuthorizationError,
    QuotaError,
    create_invitation,
    ensure_writable,
    organization_for_principal,
    require_role,
    usage_count,
)
from corpus2node.config import settings
from corpus2node.core.clock import utcnow

router = APIRouter(prefix="/organizations", tags=["organizations"])


class InvitationCreate(BaseModel):
    email: EmailStr
    role: str = "member"


class MemberRoleUpdate(BaseModel):
    role: str


class OrganizationUpdate(BaseModel):
    name: str


def _organization_view(value: Organization) -> OrganizationView:
    return OrganizationView(
        organization_id=value.organization_id,
        name=value.name,
        slug=value.slug,
        plan_code=value.plan_code,
        plan_status=value.plan_status,
        trial_ends_at=value.trial_ends_at,
        entitlements=resolve_entitlements(value),
    )


def _require_teams_enabled() -> None:
    if settings.account_product_mode != "teams":
        raise HTTPException(status_code=404, detail="Team management is not available in personal mode.")


@router.get("", response_model=list[OrganizationView])
async def list_organizations(
    principal: Principal = Depends(current_principal),
    db: AsyncSession = Depends(get_db),
) -> list[OrganizationView]:
    if settings.account_product_mode == "personal":
        organization = await db.get(Organization, principal.organization_id)
        return [_organization_view(organization)] if organization is not None else []
    organization_ids = select(Membership.organization_id).where(
        Membership.user_id == principal.user_id, Membership.status == "active"
    )
    values = (await db.scalars(select(Organization).where(Organization.organization_id.in_(organization_ids)))).all()
    return [_organization_view(value) for value in values]


@router.get("/{organization_id}/members", response_model=list[MemberView])
async def list_members(
    organization_id: str,
    principal: Principal = Depends(current_principal),
    db: AsyncSession = Depends(get_db),
) -> list[MemberView]:
    _require_teams_enabled()
    if principal.organization_id != organization_id and not principal.is_platform_admin:
        raise HTTPException(status_code=404, detail="Organization not found.")
    rows = (
        await db.execute(
            select(Membership, User)
            .join(User, User.user_id == Membership.user_id)
            .where(Membership.organization_id == organization_id)
            .order_by(Membership.joined_at)
        )
    ).all()
    return [
        MemberView(
            user_id=user.user_id,
            email=user.email,
            display_name=user.display_name,
            role=membership.role,
            status=membership.status,
        )
        for membership, user in rows
    ]


@router.post("/{organization_id}/invitations", response_model=InvitationView)
async def invite_member(
    organization_id: str,
    payload: InvitationCreate,
    principal: Principal = Depends(current_principal),
    db: AsyncSession = Depends(get_db),
) -> InvitationView:
    _require_teams_enabled()
    if principal.organization_id != organization_id:
        raise HTTPException(status_code=404, detail="Organization not found.")
    try:
        require_role(principal, "admin")
        await ensure_writable(db, principal)
        if not principal.is_platform_admin and principal.role == "admin" and payload.role not in {"member", "viewer"}:
            raise AuthorizationError("Only an organization owner can invite another administrator or owner.")
        invitation, raw = await create_invitation(
            db,
            organization_id=organization_id,
            email=str(payload.email),
            role=payload.role,
            invited_by_user_id=principal.user_id,
        )
        await db.commit()
    except QuotaError as exc:
        await db.rollback()
        raise HTTPException(
            status_code=429,
            detail=exc.detail(),
        ) from exc
    except AuthorizationError as exc:
        await db.rollback()
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except AccountError as exc:
        await db.rollback()
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    url = f"{settings.public_app_url.rstrip('/')}/activate#token={raw}"
    return InvitationView(
        invitation_id=invitation.invitation_id,
        email=invitation.email,
        role=invitation.role,
        expires_at=invitation.expires_at,
        accepted_at=invitation.accepted_at,
        activation_url=url,
    )


@router.get("/{organization_id}/invitations", response_model=list[InvitationView])
async def list_invitations(
    organization_id: str,
    principal: Principal = Depends(current_principal),
    db: AsyncSession = Depends(get_db),
) -> list[InvitationView]:
    _require_teams_enabled()
    if principal.organization_id != organization_id:
        raise HTTPException(status_code=404, detail="Organization not found.")
    try:
        require_role(principal, "admin")
    except AuthorizationError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    values = (
        await db.scalars(
            select(Invitation)
            .where(Invitation.organization_id == organization_id, Invitation.kind == "invite")
            .order_by(Invitation.created_at.desc())
        )
    ).all()
    return [
        InvitationView(
            invitation_id=value.invitation_id,
            email=value.email,
            role=value.role,
            expires_at=value.expires_at,
            accepted_at=value.accepted_at,
        )
        for value in values
    ]


@router.delete("/{organization_id}/invitations/{invitation_id}")
async def revoke_invitation(
    organization_id: str,
    invitation_id: str,
    principal: Principal = Depends(current_principal),
    db: AsyncSession = Depends(get_db),
) -> dict[str, bool]:
    _require_teams_enabled()
    if principal.organization_id != organization_id:
        raise HTTPException(status_code=404, detail="Organization not found.")
    try:
        require_role(principal, "admin")
    except AuthorizationError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    invitation = await db.get(Invitation, invitation_id)
    if invitation is None or invitation.organization_id != organization_id or invitation.accepted_at is not None:
        raise HTTPException(status_code=404, detail="Invitation not found.")
    invitation.expires_at = utcnow()
    await db.commit()
    return {"ok": True}


@router.patch("/{organization_id}/members/{user_id}", response_model=MemberView)
async def update_member(
    organization_id: str,
    user_id: str,
    payload: MemberRoleUpdate,
    principal: Principal = Depends(current_principal),
    db: AsyncSession = Depends(get_db),
) -> MemberView:
    _require_teams_enabled()
    if principal.organization_id != organization_id:
        raise HTTPException(status_code=404, detail="Organization not found.")
    try:
        require_role(principal, "owner")
        await ensure_writable(db, principal)
    except AuthorizationError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    if payload.role not in {"owner", "admin", "member", "viewer"}:
        raise HTTPException(status_code=400, detail="Invalid role.")
    membership = await db.get(Membership, (organization_id, user_id))
    user = await db.get(User, user_id)
    if membership is None or user is None:
        raise HTTPException(status_code=404, detail="Member not found.")
    if membership.role == "owner" and payload.role != "owner":
        owner_count = int(
            await db.scalar(
                select(func.count()).select_from(Membership).where(
                    Membership.organization_id == organization_id,
                    Membership.role == "owner",
                    Membership.status == "active",
                )
            )
            or 0
        )
        if owner_count <= 1:
            raise HTTPException(status_code=400, detail="An organization must keep at least one active owner.")
    membership.role = payload.role
    await db.commit()
    return MemberView(
        user_id=user.user_id,
        email=user.email,
        display_name=user.display_name,
        role=membership.role,
        status=membership.status,
    )


@router.delete("/{organization_id}/members/{user_id}")
async def deactivate_member(
    organization_id: str,
    user_id: str,
    principal: Principal = Depends(current_principal),
    db: AsyncSession = Depends(get_db),
) -> dict[str, bool]:
    _require_teams_enabled()
    if principal.organization_id != organization_id:
        raise HTTPException(status_code=404, detail="Organization not found.")
    try:
        require_role(principal, "owner")
    except AuthorizationError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    if user_id == principal.user_id:
        raise HTTPException(status_code=400, detail="The active owner cannot deactivate themselves.")
    membership = await db.get(Membership, (organization_id, user_id))
    if membership is None or membership.status != "active":
        raise HTTPException(status_code=404, detail="Member not found.")
    if membership.role == "owner":
        owner_count = int(
            await db.scalar(
                select(func.count()).select_from(Membership).where(
                    Membership.organization_id == organization_id,
                    Membership.role == "owner",
                    Membership.status == "active",
                )
            )
            or 0
        )
        if owner_count <= 1:
            raise HTTPException(status_code=400, detail="An organization must keep at least one active owner.")
    membership.status = "inactive"
    await db.commit()
    return {"ok": True}


@router.patch("/{organization_id}", response_model=OrganizationView)
async def update_organization(
    organization_id: str,
    payload: OrganizationUpdate,
    principal: Principal = Depends(current_principal),
    db: AsyncSession = Depends(get_db),
) -> OrganizationView:
    _require_teams_enabled()
    if principal.organization_id != organization_id:
        raise HTTPException(status_code=404, detail="Organization not found.")
    try:
        require_role(principal, "owner")
        await ensure_writable(db, principal)
    except AuthorizationError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    name = " ".join(payload.name.split()).strip()
    if not name or len(name) > 120:
        raise HTTPException(status_code=400, detail="Invalid organization name.")
    organization = await db.get(Organization, organization_id)
    if organization is None:
        raise HTTPException(status_code=404, detail="Organization not found.")
    organization.name = name
    await db.commit()
    return _organization_view(organization)


@router.get("/{organization_id}/usage", response_model=UsageSummary)
async def get_usage(
    organization_id: str,
    principal: Principal = Depends(current_principal),
    db: AsyncSession = Depends(get_db),
) -> UsageSummary:
    if principal.organization_id != organization_id and not principal.is_platform_admin:
        raise HTTPException(status_code=404, detail="Organization not found.")
    organization = (
        await db.get(Organization, organization_id)
        if principal.is_platform_admin
        else await organization_for_principal(db, principal)
    )
    if organization is None:
        raise HTTPException(status_code=404, detail="Organization not found.")
    storage_bytes = int(
        await db.scalar(
            select(func.coalesce(func.sum(Resource.size_bytes), 0)).where(
                Resource.organization_id == organization_id, Resource.status == "active"
            )
        )
        or 0
    )
    active_sources = int(
        await db.scalar(
            select(func.count()).select_from(Resource).where(
                Resource.organization_id == organization_id,
                Resource.resource_type == "source",
                Resource.status == "active",
            )
        )
        or 0
    )
    return UsageSummary(
        plan_code=organization.plan_code,
        period_start=utcnow().replace(day=1, hour=0, minute=0, second=0, microsecond=0),
        ai_tasks=await usage_count(db, organization_id, "ai_task"),
        chat_turns=await usage_count(db, organization_id, "chat_turn"),
        storage_bytes=storage_bytes,
        active_sources=active_sources,
        limits=resolve_entitlements(organization),
    )
