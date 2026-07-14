from __future__ import annotations

import asyncio
import hashlib
import json
import logging
from pathlib import Path
from uuid import UUID

from sqlalchemy import func, select

from corpus2node.accounts.database import session_factory
from corpus2node.accounts.entitlements import resolve_entitlements
from corpus2node.accounts.models import Organization, Project, ProjectRevision, Resource
from corpus2node.accounts.schemas import Principal
from corpus2node.accounts.service import add_activity, record_usage, register_resource
from corpus2node.config import settings
from corpus2node.core.clock import utcnow
from corpus2node.core.types import ArtifactProvenance, GraphArtifact
from corpus2node.graph.build import build_graph_artifact
from corpus2node.graph.schemas import GraphExtractionResult
from corpus2node.index.embeddings import embedding_signature, get_embeddings
from corpus2node.llm import factory
from corpus2node.llm.credentials import Purpose
from corpus2node.scientific.engine import run_scientific_analysis
from corpus2node.scientific.schemas import ScientificAnalysisRequest
from corpus2node.storage import local

logger = logging.getLogger(__name__)
_TASKS: dict[str, asyncio.Task] = {}
_DIRTY: set[str] = set()


def revision_dir(project_id: str, revision_number: int) -> Path:
    path = Path(settings.local_storage_path) / "projects" / project_id / "revisions" / str(revision_number)
    path.mkdir(parents=True, exist_ok=True)
    return path


def schedule_project_refresh(project_id: str, principal: Principal) -> None:
    existing = _TASKS.get(project_id)
    if existing is not None and not existing.done():
        _DIRTY.add(project_id)
        return

    async def runner() -> None:
        try:
            while True:
                await asyncio.sleep(max(0.0, settings.project_refresh_debounce_seconds))
                _DIRTY.discard(project_id)
                try:
                    await refresh_project(project_id, principal, automatic=True)
                except Exception:
                    logger.exception("automatic project refresh failed: project=%s", project_id)
                if project_id not in _DIRTY:
                    return
        finally:
            _TASKS.pop(project_id, None)
            _DIRTY.discard(project_id)

    _TASKS[project_id] = asyncio.create_task(runner())


async def refresh_project(
    project_id: str,
    principal: Principal,
    *,
    automatic: bool = False,
) -> ProjectRevision | None:
    from corpus2node.core.concurrency import keyed_lock

    async with keyed_lock(f"project-refresh:{project_id}"):
        async with session_factory()() as db:
            project = await db.get(Project, project_id)
            if project is None or project.organization_id != principal.organization_id or project.archived_at is not None:
                raise ValueError("Project not found.")
            organization = await db.get(Organization, project.organization_id)
            if organization is None:
                return None
            entitlements = resolve_entitlements(organization)
            if (
                organization.plan_status not in {"active", "trialing"}
                or (organization.trial_ends_at and organization.trial_ends_at <= utcnow())
                or not bool(entitlements["team_graph"])
                or (automatic and not bool(entitlements["auto_project_updates"]))
            ):
                return None
            resources = (
                await db.scalars(
                    select(Resource).where(
                        Resource.project_id == project_id,
                        Resource.resource_type == "session",
                        Resource.status == "active",
                    ).order_by(Resource.created_at)
                )
            ).all()
            session_ids = [UUID(value.resource_key) for value in resources if _session_is_graph_ready(value.resource_key)]
            contributor_user_ids = sorted({value.owner_user_id for value in resources if value.owner_user_id})
            if not session_ids:
                return None
            fingerprint = _fingerprint(session_ids)
            existing = await db.scalar(
                select(ProjectRevision).where(
                    ProjectRevision.project_id == project_id,
                    ProjectRevision.fingerprint == fingerprint,
                )
            )
            if existing is not None and existing.status != "failed":
                return existing
            if existing is None:
                revision_number = int(
                    await db.scalar(
                        select(func.coalesce(func.max(ProjectRevision.revision_number), 0)).where(
                            ProjectRevision.project_id == project_id
                        )
                    )
                    or 0
                ) + 1
                revision = ProjectRevision(
                    project_id=project_id,
                    revision_number=revision_number,
                    fingerprint=fingerprint,
                    status="running",
                    source_session_ids=[str(value) for value in session_ids],
                    contributor_user_ids=contributor_user_ids,
                    created_by_user_id=principal.user_id,
                )
                db.add(revision)
            else:
                revision = existing
                revision_number = revision.revision_number
                revision.status = "running"
                revision.error = None
                revision.completed_at = None
                revision.source_session_ids = [str(value) for value in session_ids]
                revision.contributor_user_ids = contributor_user_ids
                revision.created_by_user_id = principal.user_id
            previous_revision = await db.get(ProjectRevision, project.latest_revision_id) if project.latest_revision_id else None
            await db.commit()
            revision_id = revision.revision_id
            previous_graph_path = previous_revision.graph_artifact_path if previous_revision else ""
            previous_scientific_id = previous_revision.scientific_report_id if previous_revision else None

        try:
            graph_path, graph_summary = await asyncio.to_thread(
                _build_revision_graph, project_id, revision_number, revision_id, session_ids
            )
            scientific_report_id = None
            scientific_summary: dict[str, int] = {}
            if project.kind == "scientific":
                limit = int(entitlements["max_scientific_papers"])
                selected = session_ids[:limit]
                report = await run_scientific_analysis(ScientificAnalysisRequest(session_ids=selected))
                scientific_report_id = report.report_id
                scientific_summary = {
                    "papers": len(report.papers),
                    "claims": len(report.claims),
                    "insights": len(report.insights),
                    "opportunities": len(report.decision_cards),
                }
            delta = _revision_delta(
                graph_path,
                previous_graph_path,
                scientific_report_id,
                previous_scientific_id,
            )
        except Exception as exc:
            async with session_factory()() as db:
                failed = await db.get(ProjectRevision, revision_id)
                if failed is not None:
                    failed.status = "failed"
                    failed.error = str(exc)
                    failed.completed_at = utcnow()
                await db.commit()
            raise

        async with session_factory()() as db:
            project = await db.get(Project, project_id)
            ready = await db.get(ProjectRevision, revision_id)
            if project is None or ready is None:
                raise RuntimeError("Project revision disappeared while building.")
            ready.status = "ready"
            ready.graph_artifact_path = str(graph_path)
            ready.scientific_report_id = scientific_report_id
            ready.summary = {**graph_summary, **scientific_summary}
            ready.summary["delta"] = delta
            graph = GraphArtifact.model_validate_json(graph_path.read_text(encoding="utf-8"))
            ready.model_fingerprint = {
                "graph": graph.provenance.graph_model_signature,
                "critic": graph.provenance.critic_model_signature,
                "embedding": graph.provenance.embedding_signature,
                "graph_prompt_sha256": graph.provenance.graph_prompt_sha256,
                "critic_prompt_sha256": graph.provenance.critic_prompt_sha256,
            }
            ready.completed_at = utcnow()
            project.latest_revision_id = ready.revision_id
            project.updated_at = utcnow()
            await register_resource(
                db,
                principal=principal,
                resource_type="project_revision",
                resource_key=ready.revision_id,
                project_id=project_id,
                artifact_path=str(graph_path),
            )
            if scientific_report_id:
                await register_resource(
                    db,
                    principal=principal,
                    resource_type="scientific_report",
                    resource_key=scientific_report_id,
                    project_id=project_id,
                    artifact_path=str(local.scientific_path(scientific_report_id)),
                )
            await add_activity(
                db,
                principal,
                "project.revision_ready",
                project_id=project_id,
                resource_type="project_revision",
                resource_key=ready.revision_id,
                detail={"revision_number": revision_number, **ready.summary},
            )
            await record_usage(
                db,
                principal,
                idempotency_key=f"project-refresh:{ready.revision_id}",
                metric="ai_task",
                purpose="project_refresh",
                detail={
                    "sessions": len(ready.source_session_ids),
                    "input_chars": sum(
                        len(chunk.text)
                        for session_id in ready.source_session_ids
                        for artifact in local.list_ingest_artifacts(UUID(session_id))
                        for chunk in artifact.chunks
                    ),
                    "output_chars": len(graph_path.read_text(encoding="utf-8"))
                    + (
                        len(local.load_scientific_report(scientific_report_id).model_dump_json())
                        if scientific_report_id
                        else 0
                    ),
                },
            )
            await db.commit()
            return ready


def _session_is_graph_ready(session_id: str) -> bool:
    try:
        local.load_graph_artifact(UUID(session_id))
        return True
    except (FileNotFoundError, ValueError):
        return False


def _fingerprint(session_ids: list[UUID]) -> str:
    payload = []
    for session_id in session_ids:
        graph = local.load_graph_artifact(session_id)
        payload.append(
            {
                "session_id": str(session_id),
                "provenance": graph.provenance.model_dump(mode="json"),
            }
        )
    return hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def _build_revision_graph(
    project_id: str,
    revision_number: int,
    revision_id: str,
    session_ids: list[UUID],
) -> tuple[Path, dict[str, int]]:
    chunks = []
    candidates = []
    source_graphs: list[GraphArtifact] = []
    for session_id in session_ids:
        source_graphs.append(local.load_graph_artifact(session_id))
        chunks.extend(
            chunk for artifact in local.list_ingest_artifacts(session_id) for chunk in artifact.chunks
        )
        candidate_path = local.session_dir(session_id) / "graph_candidates.json"
        if candidate_path.exists():
            candidates.append(GraphExtractionResult.model_validate_json(candidate_path.read_text(encoding="utf-8")))
    if not candidates:
        raise ValueError("Project sessions do not contain reusable graph extraction candidates.")
    merged = GraphExtractionResult(
        concepts=[concept for value in candidates for concept in value.concepts],
        relations=[relation for value in candidates for relation in value.relations],
    )
    embeddings = get_embeddings()
    graph = build_graph_artifact(UUID(revision_id), chunks, merged, embeddings=embeddings)
    graph.provenance = _combined_provenance(source_graphs, embeddings)
    path = revision_dir(project_id, revision_number) / "graph.json"
    local.write_text_atomic(path, graph.model_dump_json(indent=2))
    return path, {
        "sessions": len(session_ids),
        "concepts": len(graph.concepts),
        "relations": len(graph.edges),
        "clusters": len(graph.topic_clusters),
    }


def _combined_provenance(source_graphs: list[GraphArtifact], embeddings) -> ArtifactProvenance:
    source_hashes = {
        key: value
        for graph in source_graphs
        for key, value in graph.provenance.source_hashes.items()
    }
    prompt_hashes = [graph.provenance.graph_prompt_sha256 for graph in source_graphs]
    critic_prompt_hashes = [graph.provenance.critic_prompt_sha256 for graph in source_graphs]
    configs = [graph.provenance.config_sha256 for graph in source_graphs]
    return ArtifactProvenance(
        pipeline_version="project-graph-v1",
        source_hashes=source_hashes,
        embedding_signature=embedding_signature(embeddings),
        graph_model_signature=factory.purpose_signature(Purpose.graph),
        critic_model_signature=factory.purpose_signature(Purpose.critic),
        graph_prompt_sha256=_hash_values(prompt_hashes),
        critic_prompt_sha256=_hash_values(critic_prompt_hashes),
        config_sha256=_hash_values(configs),
    )


def _hash_values(values: list[str]) -> str:
    return hashlib.sha256(json.dumps(sorted(values), ensure_ascii=False).encode()).hexdigest()


def _revision_delta(
    graph_path: Path,
    previous_graph_path: str,
    scientific_report_id: str | None,
    previous_scientific_id: str | None,
) -> dict[str, dict[str, int]]:
    current_graph = GraphArtifact.model_validate_json(graph_path.read_text(encoding="utf-8"))
    try:
        previous_graph = GraphArtifact.model_validate_json(Path(previous_graph_path).read_text(encoding="utf-8"))
    except (FileNotFoundError, OSError, ValueError):
        previous_graph = GraphArtifact(session_id=current_graph.session_id)
    current_concepts = {value.canonical_name for value in current_graph.concepts}
    previous_concepts = {value.canonical_name for value in previous_graph.concepts}
    current_edges = {(value.source, value.target, value.edge_type.value) for value in current_graph.edges}
    previous_edges = {(value.source, value.target, value.edge_type.value) for value in previous_graph.edges}
    current_claims, current_opportunities = _scientific_keys(scientific_report_id)
    previous_claims, previous_opportunities = _scientific_keys(previous_scientific_id)
    return {
        "concepts": _set_delta(current_concepts, previous_concepts),
        "relations": _set_delta(current_edges, previous_edges),
        "claims": _set_delta(current_claims, previous_claims),
        "opportunities": _set_delta(current_opportunities, previous_opportunities),
    }


def _scientific_keys(report_id: str | None) -> tuple[set[str], set[str]]:
    if not report_id:
        return set(), set()
    try:
        report = local.load_scientific_report(report_id)
    except FileNotFoundError:
        return set(), set()
    claims = {value.statement_zh.strip().casefold() for value in report.claims}
    opportunities = {value.title_zh.strip().casefold() for value in report.decision_cards}
    return claims, opportunities


def _set_delta(current: set, previous: set) -> dict[str, int]:
    return {"added": len(current - previous), "removed": len(previous - current)}
