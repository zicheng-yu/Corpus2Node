from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from corpus2node.accounts.database import get_db
from corpus2node.accounts.dependencies import current_principal
from corpus2node.accounts.entitlements import PLAN_CATALOG, resolve_entitlements
from corpus2node.accounts.models import Membership, Organization, User
from corpus2node.accounts.schemas import InvitationView, OrganizationView, Principal
from corpus2node.accounts.service import AccountError, create_invitation, create_organization
from corpus2node.config import settings

router = APIRouter(prefix="/admin", tags=["platform-admin"])


class OrganizationCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    owner_email: EmailStr
    plan_code: str = "team_beta"
    trial_ends_at: datetime | None = None


class OrganizationPlanUpdate(BaseModel):
    plan_code: str
    plan_status: str = "active"
    trial_ends_at: datetime | None = None
    entitlement_overrides: dict[str, int | bool] | None = None


class OrganizationProvisioned(BaseModel):
    organization: OrganizationView
    owner_invitation: InvitationView


def _require_platform_admin(principal: Principal) -> None:
    if not principal.is_platform_admin:
        raise HTTPException(status_code=403, detail="Platform administrator required.")


def _naive_utc(value: datetime | None) -> datetime | None:
    if value is None or value.tzinfo is None:
        return value
    return value.astimezone(timezone.utc).replace(tzinfo=None)


def _view(value: Organization) -> OrganizationView:
    return OrganizationView(
        organization_id=value.organization_id,
        name=value.name,
        slug=value.slug,
        plan_code=value.plan_code,
        plan_status=value.plan_status,
        trial_ends_at=value.trial_ends_at,
        entitlements=resolve_entitlements(value),
    )


@router.get("/organizations", response_model=list[OrganizationView])
async def list_all_organizations(
    principal: Principal = Depends(current_principal),
    db: AsyncSession = Depends(get_db),
) -> list[OrganizationView]:
    _require_platform_admin(principal)
    return [_view(value) for value in (await db.scalars(select(Organization).order_by(Organization.created_at))).all()]


@router.post("/organizations", response_model=OrganizationProvisioned)
async def provision_organization(
    payload: OrganizationCreate,
    principal: Principal = Depends(current_principal),
    db: AsyncSession = Depends(get_db),
) -> OrganizationProvisioned:
    _require_platform_admin(principal)
    if payload.plan_code not in PLAN_CATALOG:
        raise HTTPException(status_code=400, detail="Unknown plan code.")
    try:
        organization = await create_organization(
            db,
            name=payload.name,
            plan_code=payload.plan_code,
            trial_ends_at=_naive_utc(payload.trial_ends_at),
        )
        invitation, raw = await create_invitation(
            db,
            organization_id=organization.organization_id,
            email=str(payload.owner_email),
            role="owner",
            invited_by_user_id=principal.user_id,
        )
        await db.commit()
    except AccountError as exc:
        await db.rollback()
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return OrganizationProvisioned(
        organization=_view(organization),
        owner_invitation=InvitationView(
            invitation_id=invitation.invitation_id,
            email=invitation.email,
            role=invitation.role,
            expires_at=invitation.expires_at,
            activation_url=f"{settings.public_app_url.rstrip('/')}/activate#token={raw}",
        ),
    )


@router.patch("/organizations/{organization_id}/plan", response_model=OrganizationView)
async def update_plan(
    organization_id: str,
    payload: OrganizationPlanUpdate,
    principal: Principal = Depends(current_principal),
    db: AsyncSession = Depends(get_db),
) -> OrganizationView:
    _require_platform_admin(principal)
    if payload.plan_code not in PLAN_CATALOG:
        raise HTTPException(status_code=400, detail="Unknown plan code.")
    organization = await db.get(Organization, organization_id)
    if organization is None:
        raise HTTPException(status_code=404, detail="Organization not found.")
    organization.plan_code = payload.plan_code
    organization.plan_status = payload.plan_status
    organization.trial_ends_at = _naive_utc(payload.trial_ends_at)
    if payload.entitlement_overrides is not None:
        organization.entitlement_overrides = payload.entitlement_overrides
    await db.commit()
    return _view(organization)


@router.post("/users/{user_id}/password-reset", response_model=InvitationView)
async def create_password_reset(
    user_id: str,
    principal: Principal = Depends(current_principal),
    db: AsyncSession = Depends(get_db),
) -> InvitationView:
    _require_platform_admin(principal)
    user = await db.get(User, user_id)
    membership = await db.scalar(
        select(Membership).where(Membership.user_id == user_id, Membership.status == "active")
    )
    if user is None or membership is None:
        raise HTTPException(status_code=404, detail="User not found.")
    invitation, raw = await create_invitation(
        db,
        organization_id=membership.organization_id,
        email=user.email,
        role=membership.role,
        invited_by_user_id=principal.user_id,
        kind="reset",
        target_user_id=user.user_id,
    )
    await db.commit()
    return InvitationView(
        invitation_id=invitation.invitation_id,
        email=invitation.email,
        role=invitation.role,
        expires_at=invitation.expires_at,
        activation_url=f"{settings.public_app_url.rstrip('/')}/activate#token={raw}",
    )
