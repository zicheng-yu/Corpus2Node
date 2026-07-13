from __future__ import annotations

import hashlib
import json
from typing import Literal

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from corpus2node import jobs
from corpus2node.core.concurrency import keyed_lock
from corpus2node.core.types import DiscoveryReport, DiscoveryRequest
from corpus2node.discovery import DiscoveryInputError, deepen_proposal, make_deepener_or_none, run_discovery
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


@router.post("/run/stream")
async def run_discovery_stream(request: DiscoveryRequest) -> StreamingResponse:
    fingerprint = hashlib.sha256(
        json.dumps(request.model_dump(mode="json"), sort_keys=True, ensure_ascii=False).encode()
    ).hexdigest()

    async def runner(emit: jobs.Emit) -> None:
        emit({"type": "start", "data": {"job_id": fingerprint}})
        report = await run_discovery(request)
        local.save_discovery_report(report)
        emit({"type": "done", "data": {"report": report.model_dump(mode="json")}})

    try:
        job = jobs.start(f"discovery:{fingerprint}", runner, fingerprint=fingerprint)
    except jobs.JobConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    async def events():
        async for event in job.subscribe():
            yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"

    return StreamingResponse(events(), media_type="text/event-stream")


@router.get("")
def list_discoveries() -> list[DiscoveryReport]:
    return local.list_discovery_reports()


@router.get("/{discovery_id}")
def get_discovery(discovery_id: str) -> DiscoveryReport:
    try:
        return local.load_discovery_report(discovery_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Discovery report not found.") from exc


@router.delete("/{discovery_id}")
def delete_discovery(discovery_id: str) -> dict[str, bool]:
    try:
        local.load_discovery_report(discovery_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Discovery report not found.") from exc
    local.delete_discovery_report(discovery_id)
    return {"ok": True}


class ProposalStatusUpdate(BaseModel):
    status: Literal["new", "kept", "discarded"]


def _load_report_or_404(discovery_id: str) -> DiscoveryReport:
    try:
        return local.load_discovery_report(discovery_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Discovery report not found.") from exc


@router.patch("/{discovery_id}/proposals/{proposal_id}")
async def update_proposal_status(
    discovery_id: str, proposal_id: str, payload: ProposalStatusUpdate
) -> DiscoveryReport:
    """Persist the boss's verdict on a proposal (kept / discarded / back to new).

    Kept and discarded titles are fed into later runs over the same sets as an
    avoid-list, so reruns explore instead of repeating."""
    async with keyed_lock(f"discovery-report:{discovery_id}"):
        report = _load_report_or_404(discovery_id)
        proposal = next((p for p in report.proposals if p.proposal_id == proposal_id), None)
        if proposal is None:
            raise HTTPException(status_code=404, detail="Proposal not found in this report.")
        proposal.status = payload.status
        local.save_discovery_report(report)
        return report


@router.post("/{discovery_id}/proposals/{proposal_id}/deepen")
async def deepen_proposal_route(discovery_id: str, proposal_id: str) -> DiscoveryReport:
    """Expand one proposal into a minimal executable plan (goal/approach/data/experiment/metrics)."""
    async with keyed_lock(f"discovery-report:{discovery_id}"):
        report = _load_report_or_404(discovery_id)
        if all(p.proposal_id != proposal_id for p in report.proposals):
            raise HTTPException(status_code=404, detail="Proposal not found in this report.")
        deepener = make_deepener_or_none()
        if deepener is None:
            raise HTTPException(status_code=400, detail="深挖需要在「设置 → 模型」绑定 chat 或 critic 用途的模型。")
        try:
            report = await deepen_proposal(report, proposal_id, deepener)
        except (KeyError, ValueError) as exc:
            raise HTTPException(status_code=400, detail=f"深挖失败：{exc}") from exc
        local.save_discovery_report(report)
        return report
