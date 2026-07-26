from __future__ import annotations

import hashlib
import re
from datetime import timedelta
from pathlib import Path

from sqlalchemy import func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from corpus2node.accounts.entitlements import resolve_entitlements
from corpus2node.accounts.models import (
    ActivityEvent,
    AuthSession,
    Invitation,
    Membership,
    Organization,
    Project,
    Resource,
    ShareLink,
    UsageEvent,
    User,
)
from corpus2node.accounts.schemas import CurrentUser, MembershipView, Principal
from corpus2node.accounts.security import hash_password, hash_token, normalize_email, random_token, verify_password
from corpus2node.config import settings
from corpus2node.core.clock import utcnow

ROLE_RANK = {"viewer": 0, "member": 1, "admin": 2, "owner": 3}


class AccountError(ValueError):
    pass


class AuthenticationError(AccountError):
    pass


class AuthorizationError(AccountError):
    pass


class QuotaError(AccountError):
    def __init__(self, metric: str, used: int, limit: int) -> None:
        super().__init__(f"Quota exceeded for {metric}: {used}/{limit}")
        self.metric = metric
        self.used = used
        self.limit = limit

    def detail(self) -> dict[str, str | int | None]:
        now = utcnow()
        reset_at = None
        if self.metric in {"ai_task", "chat_turn"}:
            if now.month == 12:
                reset_at = now.replace(year=now.year + 1, month=1, day=1, hour=0, minute=0, second=0, microsecond=0)
            else:
                reset_at = now.replace(month=now.month + 1, day=1, hour=0, minute=0, second=0, microsecond=0)
        return {
            "code": "quota_exceeded",
            "metric": self.metric,
            "used": self.used,
            "limit": self.limit,
            "reset_at": reset_at.isoformat() if reset_at else None,
        }


def _slug(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.casefold()).strip("-")
    return slug[:60] or f"org-{random_token()[:8].lower()}"


async def create_organization(
    db: AsyncSession,
    *,
    name: str,
    plan_code: str = "free",
    slug: str = "",
    trial_ends_at=None,
    entitlement_overrides: dict | None = None,
    personal_owner_user_id: str | None = None,
) -> Organization:
    clean_name = " ".join(name.split()).strip()
    if not clean_name:
        raise AccountError("Organization name cannot be empty.")
    base = _slug(slug or clean_name)
    candidate = base
    suffix = 2
    while await db.scalar(select(Organization.organization_id).where(Organization.slug == candidate)):
        candidate = f"{base[:54]}-{suffix}"
        suffix += 1
    organization = Organization(
        name=clean_name[:120],
        slug=candidate,
        plan_code=plan_code,
        trial_ends_at=trial_ends_at,
        entitlement_overrides=entitlement_overrides or {},
        personal_owner_user_id=personal_owner_user_id,
    )
    db.add(organization)
    await db.flush()
    return organization


async def create_invitation(
    db: AsyncSession,
    *,
    organization_id: str,
    email: str,
    role: str,
    invited_by_user_id: str | None,
    make_platform_admin: bool = False,
    kind: str = "invite",
    target_user_id: str | None = None,
) -> tuple[Invitation, str]:
    if role not in ROLE_RANK:
        raise AccountError("Invalid organization role.")
    organization = await db.get(Organization, organization_id)
    if organization is None:
        raise AccountError("Organization not found.")
    email = normalize_email(email)
    if kind == "invite":
        existing_user_id = await db.scalar(select(User.user_id).where(User.email == email))
        if existing_user_id and await db.get(Membership, (organization_id, existing_user_id)):
            raise AccountError("This user is already a member.")
        limit = int(resolve_entitlements(organization)["max_members"])
        active = int(
            await db.scalar(
                select(func.count()).select_from(Membership).where(
                    Membership.organization_id == organization_id,
                    Membership.status == "active",
                )
            )
            or 0
        )
        pending = int(
            await db.scalar(
                select(func.count()).select_from(Invitation).where(
                    Invitation.organization_id == organization_id,
                    Invitation.accepted_at.is_(None),
                    Invitation.expires_at > utcnow(),
                    Invitation.kind == "invite",
                )
            )
            or 0
        )
        if active + pending >= limit:
            raise QuotaError("members", active + pending, limit)
    raw_token = random_token()
    invitation = Invitation(
        organization_id=organization_id,
        email=email,
        role=role,
        kind=kind,
        token_hash=hash_token(raw_token),
        invited_by_user_id=invited_by_user_id,
        target_user_id=target_user_id,
        make_platform_admin=make_platform_admin,
        expires_at=utcnow() + timedelta(days=settings.invitation_expiry_days),
    )
    db.add(invitation)
    await db.flush()
    return invitation, raw_token


async def activate_invitation(
    db: AsyncSession, *, token: str, display_name: str, password: str
) -> User:
    invitation = await db.scalar(select(Invitation).where(Invitation.token_hash == hash_token(token)))
    now = utcnow()
    if invitation is None or invitation.accepted_at is not None or invitation.expires_at <= now:
        raise AuthenticationError("Invitation is invalid or expired.")
    user = await db.scalar(select(User).where(User.email == invitation.email))
    if invitation.kind == "reset":
        if user is None or (invitation.target_user_id and user.user_id != invitation.target_user_id):
            raise AuthenticationError("Password reset link is invalid.")
    elif user is None:
        user = User(email=invitation.email)
        db.add(user)
        await db.flush()
    user.display_name = " ".join(display_name.split()).strip()[:120]
    user.password_hash = hash_password(password)
    user.status = "active"
    await db.execute(
        update(AuthSession)
        .where(AuthSession.user_id == user.user_id, AuthSession.revoked_at.is_(None))
        .values(revoked_at=now)
    )
    if invitation.make_platform_admin:
        user.is_platform_admin = True
    if invitation.kind == "invite" and await db.get(Membership, (invitation.organization_id, user.user_id)) is None:
        db.add(Membership(organization_id=invitation.organization_id, user_id=user.user_id, role=invitation.role))
    invitation.accepted_at = now
    await db.flush()
    return user


async def authenticate(db: AsyncSession, email: str, password: str) -> User:
    user = await db.scalar(select(User).where(User.email == normalize_email(email)))
    encoded = user.password_hash if user is not None else ""
    if not verify_password(password, encoded) or user is None or user.status != "active":
        raise AuthenticationError("Invalid email or password.")
    return user


async def create_auth_session(db: AsyncSession, user_id: str) -> tuple[AuthSession, str, str]:
    token = random_token()
    csrf = random_token()
    auth_session = AuthSession(
        user_id=user_id,
        token_hash=hash_token(token),
        csrf_hash=hash_token(csrf),
        expires_at=utcnow() + timedelta(days=settings.auth_session_days),
    )
    db.add(auth_session)
    await db.flush()
    return auth_session, token, csrf


async def revoke_auth_session(db: AsyncSession, token: str) -> None:
    auth_session = await db.scalar(select(AuthSession).where(AuthSession.token_hash == hash_token(token)))
    if auth_session is not None:
        auth_session.revoked_at = utcnow()


async def validate_csrf(db: AsyncSession, token: str, csrf: str) -> bool:
    if not token or not csrf:
        return False
    stored = await db.scalar(
        select(AuthSession.csrf_hash).where(
            AuthSession.token_hash == hash_token(token),
            AuthSession.revoked_at.is_(None),
            AuthSession.expires_at > utcnow(),
        )
    )
    return stored == hash_token(csrf)


async def resolve_principal(db: AsyncSession, token: str, requested_org_id: str | None) -> Principal | None:
    now = utcnow()
    row = (
        await db.execute(
            select(AuthSession, User)
            .join(User, User.user_id == AuthSession.user_id)
            .where(
                AuthSession.token_hash == hash_token(token),
                AuthSession.revoked_at.is_(None),
                AuthSession.expires_at > now,
                User.status == "active",
            )
        )
    ).first()
    if row is None:
        return None
    auth_session, user = row
    if settings.account_product_mode == "personal":
        selected, _ = await ensure_personal_organization(db, user)
        auth_session.last_seen_at = now
        return Principal(
            user_id=user.user_id,
            email=user.email,
            display_name=user.display_name,
            organization_id=selected.organization_id,
            role="owner",
            is_platform_admin=user.is_platform_admin,
        )
    memberships = (
        await db.execute(
            select(Membership)
            .where(Membership.user_id == user.user_id, Membership.status == "active")
            .order_by(Membership.joined_at)
        )
    ).scalars().all()
    selected = None
    if requested_org_id:
        selected = next((item for item in memberships if item.organization_id == requested_org_id), None)
        if selected is None and not user.is_platform_admin:
            return None
    elif memberships:
        selected = memberships[0]
    auth_session.last_seen_at = now
    return Principal(
        user_id=user.user_id,
        email=user.email,
        display_name=user.display_name,
        organization_id=requested_org_id if user.is_platform_admin and requested_org_id else (
            selected.organization_id if selected else None
        ),
        role=selected.role if selected else None,
        is_platform_admin=user.is_platform_admin,
    )


async def current_user_view(db: AsyncSession, principal: Principal) -> CurrentUser:
    query = (
        select(Membership, Organization)
        .join(Organization, Organization.organization_id == Membership.organization_id)
        .where(Membership.user_id == principal.user_id, Membership.status == "active")
        .order_by(Membership.joined_at)
    )
    if settings.account_product_mode == "personal":
        query = query.where(Membership.organization_id == principal.organization_id)
    rows = (await db.execute(query)).all()
    return CurrentUser(
        user_id=principal.user_id,
        email=principal.email,
        display_name=principal.display_name,
        is_platform_admin=principal.is_platform_admin,
        active_organization_id=principal.organization_id,
        memberships=[
            MembershipView(
                organization_id=organization.organization_id,
                organization_name=organization.name,
                organization_slug=organization.slug,
                role=membership.role,
            )
            for membership, organization in rows
        ],
    )


async def ensure_personal_organization(
    db: AsyncSession,
    user: User,
) -> tuple[Membership, Organization]:
    """Return the account's private workspace, creating one when necessary.

    Existing owner workspaces are adopted so migrated artifacts stay with their
    original owner. Shared memberships are never selected as a personal workspace.
    """
    organization = None
    if user.personal_organization_id:
        candidate = await db.get(Organization, user.personal_organization_id)
        if (
            candidate is not None
            and candidate.slug != "platform"
            and candidate.personal_owner_user_id in {None, user.user_id}
        ):
            organization = candidate

    if organization is None:
        organization = await db.scalar(
            select(Organization)
            .join(Membership, Membership.organization_id == Organization.organization_id)
            .where(
                Membership.user_id == user.user_id,
                Membership.status == "active",
                Membership.role == "owner",
                Organization.slug != "platform",
                or_(
                    Organization.personal_owner_user_id.is_(None),
                    Organization.personal_owner_user_id == user.user_id,
                ),
            )
            .order_by(Membership.joined_at)
        )

    if organization is None:
        owner_label = (user.display_name or user.email.split("@", 1)[0]).strip()
        organization = await create_organization(
            db,
            name=f"{owner_label} 的资料库",
            slug=f"personal-{user.user_id}",
            plan_code="free",
            personal_owner_user_id=user.user_id,
        )
    else:
        organization.personal_owner_user_id = user.user_id

    membership = await db.get(Membership, (organization.organization_id, user.user_id))
    if membership is None:
        membership = Membership(
            organization_id=organization.organization_id,
            user_id=user.user_id,
            role="owner",
        )
        db.add(membership)
    else:
        membership.role = "owner"
        membership.status = "active"
    user.personal_organization_id = organization.organization_id
    await db.flush()
    return membership, organization


def require_role(principal: Principal, minimum: str) -> None:
    if principal.is_platform_admin:
        return
    if principal.role is None or ROLE_RANK.get(principal.role, -1) < ROLE_RANK[minimum]:
        raise AuthorizationError("Insufficient organization role.")


async def register_resource(
    db: AsyncSession,
    *,
    principal: Principal,
    resource_type: str,
    resource_key: str,
    project_id: str | None = None,
    artifact_path: str = "",
    owner_user_id: str | None = None,
    size_bytes: int = 0,
) -> Resource:
    if principal.organization_id is None:
        raise AuthorizationError("An active organization is required.")
    size_bytes = size_bytes or artifact_size(artifact_path)
    existing = await db.scalar(
        select(Resource).where(Resource.resource_type == resource_type, Resource.resource_key == resource_key)
    )
    if existing is not None:
        if existing.organization_id != principal.organization_id:
            raise AuthorizationError("Resource belongs to another organization.")
        previous_size = existing.size_bytes
        existing.project_id = project_id or existing.project_id
        existing.owner_user_id = owner_user_id if owner_user_id is not None else existing.owner_user_id
        existing.artifact_path = artifact_path or existing.artifact_path
        existing.size_bytes = size_bytes or existing.size_bytes
        existing.status = "active"
        await _record_resource_storage_delta(
            db,
            principal,
            resource_type,
            resource_key,
            previous_size,
            existing.size_bytes,
        )
        return existing
    resource = Resource(
        resource_type=resource_type,
        resource_key=resource_key,
        organization_id=principal.organization_id,
        project_id=project_id,
        owner_user_id=owner_user_id,
        artifact_path=artifact_path,
        size_bytes=size_bytes,
    )
    db.add(resource)
    await db.flush()
    await _record_resource_storage_delta(
        db,
        principal,
        resource_type,
        resource_key,
        0,
        size_bytes,
    )
    return resource


async def _record_resource_storage_delta(
    db: AsyncSession,
    principal: Principal,
    resource_type: str,
    resource_key: str,
    previous_size: int,
    current_size: int,
) -> None:
    # Source uploads have their own request/file-size event at the upload boundary.
    quantity = current_size - previous_size
    if not quantity or resource_type == "source" or principal.organization_id is None:
        return
    signature = hashlib.sha256(
        f"{resource_type}:{resource_key}:{previous_size}:{current_size}".encode()
    ).hexdigest()
    idempotency_key = f"resource-storage:{signature}"
    if await db.scalar(
        select(UsageEvent.usage_id).where(UsageEvent.idempotency_key == idempotency_key)
    ):
        return
    db.add(
        UsageEvent(
            organization_id=principal.organization_id,
            user_id=principal.user_id,
            idempotency_key=idempotency_key,
            metric="storage_growth",
            quantity=quantity,
            purpose="storage",
            detail={"resource_type": resource_type, "resource_key": resource_key},
        )
    )


async def resource_for_principal(
    db: AsyncSession,
    principal: Principal,
    resource_type: str,
    resource_key: str,
    *,
    owner_only: bool = False,
) -> Resource | None:
    resource = await db.scalar(
        select(Resource).where(
            Resource.resource_type == resource_type,
            Resource.resource_key == str(resource_key),
            Resource.status == "active",
        )
    )
    if resource is None or resource.organization_id != principal.organization_id:
        return None
    if owner_only and resource.owner_user_id != principal.user_id:
        return None
    return resource


async def authorized_resource_keys(db: AsyncSession, principal: Principal, resource_type: str) -> list[str]:
    conditions = [
        Resource.organization_id == principal.organization_id,
        Resource.resource_type == resource_type,
        Resource.status == "active",
    ]
    if resource_type in {"chat", "note", "test", "prompt_settings"}:
        conditions.append(Resource.owner_user_id == principal.user_id)
    return list((await db.scalars(select(Resource.resource_key).where(*conditions))).all())


async def add_activity(
    db: AsyncSession,
    principal: Principal,
    action: str,
    *,
    project_id: str | None = None,
    resource_type: str = "",
    resource_key: str = "",
    detail: dict | None = None,
) -> ActivityEvent:
    if principal.organization_id is None:
        raise AuthorizationError("An active organization is required.")
    event = ActivityEvent(
        organization_id=principal.organization_id,
        project_id=project_id,
        actor_user_id=principal.user_id,
        action=action,
        resource_type=resource_type,
        resource_key=resource_key,
        detail=detail or {},
    )
    db.add(event)
    await db.flush()
    return event


async def organization_for_principal(db: AsyncSession, principal: Principal) -> Organization:
    if principal.organization_id is None:
        raise AuthorizationError("An active organization is required.")
    organization = await db.get(Organization, principal.organization_id)
    if organization is None:
        raise AuthorizationError("Organization not found.")
    return organization


async def ensure_writable(db: AsyncSession, principal: Principal) -> Organization:
    organization = await organization_for_principal(db, principal)
    if organization.plan_status not in {"active", "trialing"} or (
        organization.trial_ends_at and organization.trial_ends_at <= utcnow()
    ):
        raise AuthorizationError("Organization is read-only because its plan is inactive.")
    entitlements = resolve_entitlements(organization)
    member_count = int(
        await db.scalar(
            select(func.count()).select_from(Membership).where(
                Membership.organization_id == organization.organization_id,
                Membership.status == "active",
            )
        )
        or 0
    )
    project_count = int(
        await db.scalar(
            select(func.count()).select_from(Project).where(
                Project.organization_id == organization.organization_id,
                Project.archived_at.is_(None),
            )
        )
        or 0
    )
    source_count = int(
        await db.scalar(
            select(func.count()).select_from(Resource).where(
                Resource.organization_id == organization.organization_id,
                Resource.resource_type == "source",
                Resource.status == "active",
            )
        )
        or 0
    )
    storage_bytes = int(
        await db.scalar(
            select(func.coalesce(func.sum(Resource.size_bytes), 0)).where(
                Resource.organization_id == organization.organization_id,
                Resource.status == "active",
            )
        )
        or 0
    )
    overages = {
        "members": (member_count, int(entitlements["max_members"])),
        "projects": (project_count, int(entitlements["max_projects"])),
        "active_sources": (source_count, int(entitlements["max_active_sources"])),
        "storage_bytes": (storage_bytes, int(entitlements["max_storage_bytes"])),
    }
    exceeded = next((name for name, (used, limit) in overages.items() if used > limit), None)
    if exceeded:
        used, limit = overages[exceeded]
        raise AuthorizationError(
            f"Organization is read-only because {exceeded} exceeds its plan limit ({used}/{limit})."
        )
    return organization


async def usage_count(db: AsyncSession, organization_id: str, metric: str) -> int:
    start = utcnow().replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    return int(
        await db.scalar(
            select(func.coalesce(func.sum(UsageEvent.quantity), 0)).where(
                UsageEvent.organization_id == organization_id,
                UsageEvent.metric == metric,
                UsageEvent.created_at >= start,
            )
        )
        or 0
    )


async def enforce_quota(db: AsyncSession, principal: Principal, metric: str) -> None:
    organization = await ensure_writable(db, principal)
    limit_key = {"ai_task": "max_ai_tasks_month", "chat_turn": "max_chat_turns_month"}[metric]
    limit = int(resolve_entitlements(organization)[limit_key])
    used = await usage_count(db, organization.organization_id, metric)
    if used >= limit:
        raise QuotaError(metric, used, limit)


async def record_usage(
    db: AsyncSession,
    principal: Principal,
    *,
    idempotency_key: str,
    metric: str,
    quantity: int = 1,
    purpose: str = "",
    detail: dict | None = None,
) -> None:
    if principal.organization_id is None:
        return
    if await db.scalar(select(UsageEvent.usage_id).where(UsageEvent.idempotency_key == idempotency_key)):
        return
    usage_detail = dict(detail or {})
    purpose_map = {
        "graph": "graph",
        "project_refresh": "graph",
        "chat": "chat",
        "project_chat": "chat",
        "notes": "graph",
        "test": "exam",
        "scientific": "graph",
        "discovery": "graph",
    }
    model_purpose = purpose_map.get(purpose)
    if model_purpose:
        from corpus2node.llm import factory, store
        from corpus2node.llm.credentials import Purpose

        if store.active_user_id() == principal.user_id:
            signature = factory.purpose_signature(Purpose(model_purpose))
        else:
            with store.user_scope(principal.user_id):
                signature = factory.purpose_signature(Purpose(model_purpose))
        usage_detail.setdefault("model_signature", signature)
    if "input_chars" in usage_detail and "input_tokens" not in usage_detail:
        usage_detail["input_tokens"] = max(1, int(usage_detail["input_chars"]) // 4)
        usage_detail["tokens_estimated"] = True
    if "output_chars" in usage_detail and "output_tokens" not in usage_detail:
        usage_detail["output_tokens"] = max(1, int(usage_detail["output_chars"]) // 4)
        usage_detail["tokens_estimated"] = True
    if "total_tokens" not in usage_detail and (
        "input_tokens" in usage_detail or "output_tokens" in usage_detail
    ):
        usage_detail["total_tokens"] = int(usage_detail.get("input_tokens", 0)) + int(
            usage_detail.get("output_tokens", 0)
        )
    db.add(
        UsageEvent(
            organization_id=principal.organization_id,
            user_id=principal.user_id,
            idempotency_key=idempotency_key,
            metric=metric,
            quantity=quantity,
            purpose=purpose,
            detail=usage_detail,
        )
    )


def artifact_size(path: str) -> int:
    try:
        candidate = Path(path)
        if candidate.is_file():
            return candidate.stat().st_size
    except OSError:
        pass
    return 0


async def active_share_count(db: AsyncSession, organization_id: str) -> int:
    return int(
        await db.scalar(
            select(func.count()).select_from(ShareLink).where(
                ShareLink.organization_id == organization_id,
                ShareLink.revoked_at.is_(None),
                ShareLink.expires_at > utcnow(),
            )
        )
        or 0
    )
