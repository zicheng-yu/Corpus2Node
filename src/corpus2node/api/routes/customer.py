"""Public customer profile endpoint for brand / persona landings."""

from __future__ import annotations

from fastapi import APIRouter

from corpus2node.customization.profile import get_customer_profile

router = APIRouter(tags=["customer"])


@router.get("/customer-profile")
async def customer_profile() -> dict:
    """Return the active customer brand, personas, landings, and feature flags."""
    return get_customer_profile().public_dict()
