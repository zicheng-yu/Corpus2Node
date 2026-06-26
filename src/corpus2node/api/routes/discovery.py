from __future__ import annotations

from fastapi import APIRouter, HTTPException

from corpus2node.core.types import DiscoveryReport, DiscoveryRequest
from corpus2node.discovery import DiscoveryInputError, run_discovery
from corpus2node.storage import local

router = APIRouter(prefix="/discovery", tags=["discovery"])


@router.post("/run")
async def run_discovery_route(request: DiscoveryRequest) -> DiscoveryReport:
    try:
        report = await run_discovery(request)
    except DiscoveryInputError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    local.save_discovery_report(report)
    return report


@router.get("")
def list_discoveries() -> list[DiscoveryReport]:
    return local.list_discovery_reports()


@router.get("/{discovery_id}")
def get_discovery(discovery_id: str) -> DiscoveryReport:
    try:
        return local.load_discovery_report(discovery_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Discovery report not found.") from exc
