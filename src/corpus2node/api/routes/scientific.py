from __future__ import annotations

import asyncio
from pathlib import Path
from uuid import UUID

from fastapi import APIRouter, HTTPException

from corpus2node.config import settings
from corpus2node.scientific.engine import ScientificInputError, run_scientific_analysis
from corpus2node.scientific.parsers import ScientificParseError, parse_grobid_pdf, parse_scientific_xml
from corpus2node.scientific.schemas import (
    ScientificAnalysisRequest,
    ScientificDocument,
    ScientificParseRequest,
    ScientificReport,
)
from corpus2node.storage import local

router = APIRouter(prefix="/scientific", tags=["scientific"])


@router.post("/run")
async def run_scientific_route(request: ScientificAnalysisRequest) -> ScientificReport:
    try:
        return await run_scientific_analysis(request)
    except ScientificInputError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/parse")
async def parse_scientific_sources(request: ScientificParseRequest) -> list[ScientificDocument]:
    try:
        session = local.load_session(request.session_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="资料集不存在。") from exc
    requested = {str(value) for value in request.source_ids}
    sources = [value for value in session.source_files if not requested or str(value.source_id) in requested]
    if not sources:
        raise HTTPException(status_code=400, detail="没有可解析的指定文献。")
    documents: list[ScientificDocument] = []
    try:
        for source in sources:
            suffix = Path(source.filename).suffix.lower()
            if suffix in {".xml", ".nxml"}:
                document = await asyncio.to_thread(
                    parse_scientific_xml, source.storage_path, source_id=str(source.source_id)
                )
            elif suffix == ".pdf":
                document = await asyncio.to_thread(
                    parse_grobid_pdf,
                    source.storage_path,
                    source_id=str(source.source_id),
                    base_url=settings.grobid_base_url,
                )
            else:
                continue
            local.save_scientific_document(request.session_id, document)
            documents.append(document)
    except ScientificParseError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    if not documents:
        raise HTTPException(status_code=400, detail="仅支持 JATS/XML、TEI/XML 或 PDF 科研结构解析。")
    return documents


@router.get("/documents/{session_id}")
def list_scientific_documents(session_id: UUID) -> list[ScientificDocument]:
    try:
        local.load_session(session_id)
        return local.list_scientific_documents(session_id)
    except (FileNotFoundError, ValueError) as exc:
        raise HTTPException(status_code=404, detail="资料集不存在。") from exc


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
