from __future__ import annotations

from corpus2node.accounts.models import Organization

PLAN_CATALOG: dict[str, dict[str, int | bool]] = {
    "free": {
        "max_members": 1,
        "max_projects": 1,
        "max_active_sources": 20,
        "max_storage_bytes": 1024**3,
        "max_ai_tasks_month": 50,
        "max_chat_turns_month": 200,
        "max_scientific_papers": 3,
        "max_active_shares": 1,
        "max_share_days": 7,
        "team_graph": False,
        "auto_project_updates": False,
    },
    "team_beta": {
        "max_members": 10,
        "max_projects": 10,
        "max_active_sources": 500,
        "max_storage_bytes": 20 * 1024**3,
        "max_ai_tasks_month": 1000,
        "max_chat_turns_month": 5000,
        "max_scientific_papers": 100,
        "max_active_shares": 50,
        "max_share_days": 90,
        "team_graph": True,
        "auto_project_updates": True,
    },
}


def resolve_entitlements(organization: Organization) -> dict[str, int | bool]:
    values = dict(PLAN_CATALOG.get(organization.plan_code, PLAN_CATALOG["free"]))
    values.update(organization.entitlement_overrides or {})
    return values
