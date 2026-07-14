from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from corpus2node.accounts.database import get_db
from corpus2node.accounts.dependencies import optional_principal
from corpus2node.accounts.service import AuthorizationError, ensure_writable, register_resource
from corpus2node import prompt_store
from corpus2node.prompt_store import PromptSettings

router = APIRouter(prefix="/settings/prompts", tags=["settings"])


@router.get("")
def get_prompts(request: Request) -> PromptSettings:
    principal = optional_principal(request)
    owner_key = (
        f"{principal.organization_id}/{principal.user_id}"
        if principal is not None and principal.organization_id is not None
        else None
    )
    return prompt_store.load(owner_key)


@router.put("")
async def set_prompts(
    payload: PromptSettings,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> PromptSettings:
    principal = optional_principal(request)
    owner_key = (
        f"{principal.organization_id}/{principal.user_id}"
        if principal is not None and principal.organization_id is not None
        else None
    )
    if principal is not None:
        try:
            await ensure_writable(db, principal)
        except AuthorizationError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
    value = prompt_store.save(payload, owner_key)
    if principal is not None and owner_key is not None:
        await register_resource(
            db,
            principal=principal,
            resource_type="prompt_settings",
            resource_key=principal.user_id,
            owner_user_id=principal.user_id,
            artifact_path=str(prompt_store.settings_path(owner_key)),
        )
        await db.commit()
    return value
