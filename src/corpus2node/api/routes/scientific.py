from __future__ import annotations

from fastapi import APIRouter, HTTPException

from corpus2node.scientific.engine import ScientificInputError, run_scientific_analysis
from corpus2node.scientific.schemas import ScientificAnalysisRequest, ScientificReport
from corpus2node.storage import local

router = APIRouter(prefix="/scientific", tags=["scientific"])


@router.post("/run")
async def run_scientific_route(request: ScientificAnalysisRequest) -> ScientificReport:
    try:
        return await run_scientific_analysis(request)
    except ScientificInputError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("")
def list_scientific_reports() -> list[ScientificReport]:
    return local.list_scientific_reports()


@router.get("/{report_id}")
def get_scientific_report(report_id: str) -> ScientificReport:
    try:
        return local.load_scientific_report(report_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="科研证据报告不存在。") from exc


@router.delete("/{report_id}")
def delete_scientific_report(report_id: str) -> dict[str, bool]:
    try:
        local.load_scientific_report(report_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="科研证据报告不存在。") from exc
    local.delete_scientific_report(report_id)
    return {"ok": True}
