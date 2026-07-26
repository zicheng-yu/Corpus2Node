from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, EmailStr, Field

Role = Literal["owner", "admin", "member", "viewer"]
Persona = Literal["executive", "researcher", "operator"]


@dataclass(frozen=True)
class Principal:
    user_id: str
    email: str
    display_name: str
    organization_id: str | None
    role: str | None
    is_platform_admin: bool = False
    persona: str = "operator"


class MembershipView(BaseModel):
    organization_id: str
    organization_name: str
    organization_slug: str
    role: str


class CurrentUser(BaseModel):
    user_id: str
    email: EmailStr
    display_name: str
    is_platform_admin: bool = False
    persona: Persona = "operator"
    active_organization_id: str | None = None
    memberships: list[MembershipView] = Field(default_factory=list)


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=12, max_length=128)


class ActivateRequest(BaseModel):
    token: str = Field(min_length=32, max_length=256)
    display_name: str = Field(min_length=1, max_length=120)
    password: str = Field(min_length=12, max_length=128)


class ChangePasswordRequest(BaseModel):
    current_password: str = Field(min_length=12, max_length=128)
    new_password: str = Field(min_length=12, max_length=128)


class InvitationView(BaseModel):
    invitation_id: str
    email: EmailStr
    role: str
    expires_at: datetime
    accepted_at: datetime | None = None
    activation_url: str | None = None


class OrganizationView(BaseModel):
    organization_id: str
    name: str
    slug: str
    plan_code: str
    plan_status: str
    trial_ends_at: datetime | None = None
    entitlements: dict[str, int | bool]


class MemberView(BaseModel):
    user_id: str
    email: EmailStr
    display_name: str
    role: str
    status: str


class ProjectView(BaseModel):
    project_id: str
    organization_id: str
    name: str
    description: str = ""
    kind: str
    latest_revision_id: str | None = None
    created_at: datetime
    updated_at: datetime
    session_count: int = 0


class ProjectRevisionView(BaseModel):
    revision_id: str
    project_id: str
    revision_number: int
    status: str
    source_session_ids: list[str]
    contributor_user_ids: list[str] = Field(default_factory=list)
    scientific_report_id: str | None = None
    summary: dict = Field(default_factory=dict)
    model_fingerprint: dict = Field(default_factory=dict)
    error: str | None = None
    created_at: datetime
    completed_at: datetime | None = None


class ActivityEventView(BaseModel):
    event_id: str
    actor_user_id: str | None = None
    action: str
    resource_type: str
    resource_key: str
    detail: dict = Field(default_factory=dict)
    created_at: datetime


class UsageSummary(BaseModel):
    plan_code: str
    period_start: datetime
    ai_tasks: int = 0
    chat_turns: int = 0
    storage_bytes: int = 0
    active_sources: int = 0
    limits: dict[str, int | bool] = Field(default_factory=dict)


class ShareLinkView(BaseModel):
    share_id: str
    resource_type: str
    resource_key: str
    expires_at: datetime
    revoked_at: datetime | None = None
    share_url: str | None = None


class ShareSnapshot(BaseModel):
    resource_type: str
    title: str
    payload: dict
    expires_at: datetime
