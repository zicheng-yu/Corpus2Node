from __future__ import annotations

from fastapi import HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from corpus2node.accounts.models import Resource
from corpus2node.accounts.schemas import Principal
from corpus2node.accounts.service import resource_for_principal
from corpus2node.config import settings


def current_principal(request: Request) -> Principal:
    principal = getattr(request.state, "principal", None)
    if principal is None:
        raise HTTPException(status_code=401, detail="Authentication required.")
    return principal


def optional_principal(request: Request) -> Principal | None:
    if settings.auth_mode != "accounts":
        return None
    return getattr(request.state, "principal", None)


async def require_resource_access(
    request: Request,
    db: AsyncSession,
    resource_type: str,
    resource_key: str,
    *,
    owner_only: bool = False,
) -> Resource | None:
    principal = optional_principal(request)
    if principal is None:
        return None
    resource = await resource_for_principal(
        db, principal, resource_type, str(resource_key), owner_only=owner_only
    )
    if resource is None:
        raise HTTPException(status_code=404, detail="Resource not found.")
    return resource
