from __future__ import annotations

import asyncio
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import func, select

from corpus2node.accounts.database import dispose_db, init_db, session_factory
from corpus2node.accounts.models import Organization, Project, ProjectRevision, Resource
from corpus2node.accounts.schemas import Principal
from corpus2node.config import settings
from corpus2node.core.types import ArtifactProvenance, CourseSession, EvidenceChunk, IngestArtifact, SourceKind
from corpus2node.graph.build import build_graph_artifact
from corpus2node.graph.schemas import ExtractedConcept, GraphExtractionResult
from corpus2node.index.embeddings import HashingEmbeddings
from corpus2node.projects import revisions
from corpus2node.storage import local


def _seed_graph_ready_session(title: str, concept_name: str):
    session = CourseSession(course_title="Team Research", lecture_title=title)
    local.save_session(session)
    source_id = uuid4()
    chunk = EvidenceChunk(
        chunk_id=f"{session.session_id}-chunk",
        source_id=str(source_id),
        source_type=SourceKind.document,
        text=f"{concept_name} 是该论文中的核心方法与证据。",
        summary=concept_name,
    )
    local.save_ingest_artifact(
        IngestArtifact(
            session_id=session.session_id,
            source_id=source_id,
            source_kind=SourceKind.document,
            chunks=[chunk],
        )
    )
    candidates = GraphExtractionResult(
        concepts=[
            ExtractedConcept(
                name=concept_name,
                canonical_name=concept_name,
                definition=f"{concept_name} 的定义",
            )
        ]
    )
    local.write_text_atomic(
        local.session_dir(session.session_id) / "graph_candidates.json",
        candidates.model_dump_json(indent=2),
    )
    graph = build_graph_artifact(
        session.session_id,
        [chunk],
        candidates,
        embeddings=HashingEmbeddings(dims=64),
    )
    graph.provenance = ArtifactProvenance(source_hashes={str(source_id): concept_name})
    local.save_graph_artifact(graph)
    return session


async def _revision_scenario(monkeypatch):
    await init_db()
    first = _seed_graph_ready_session("Paper A", "方法甲")
    second = _seed_graph_ready_session("Paper B", "方法乙")
    async with session_factory()() as db:
        organization = Organization(name="Team", slug="team", plan_code="team_beta")
        db.add(organization)
        await db.flush()
        project = Project(
            organization_id=organization.organization_id,
            name="Team Research",
            kind="general",
            created_by_user_id="user-a",
        )
        db.add(project)
        await db.flush()
        db.add_all(
            [
                Resource(
                    organization_id=organization.organization_id,
                    project_id=project.project_id,
                    owner_user_id=owner,
                    resource_type="session",
                    resource_key=str(session.session_id),
                    artifact_path=str(local.session_path(session.session_id)),
                )
                for session, owner in ((first, "user-a"), (second, "user-b"))
            ]
        )
        await db.commit()
        organization_id = organization.organization_id
        project_id = project.project_id
    principal = Principal(
        user_id="user-a",
        email="a@example.com",
        display_name="A",
        organization_id=organization_id,
        role="member",
    )

    revisions.schedule_project_refresh(project_id, principal)
    revisions.schedule_project_refresh(project_id, principal)
    task = revisions._TASKS[project_id]
    await task

    async with session_factory()() as db:
        values = (await db.scalars(select(ProjectRevision).where(ProjectRevision.project_id == project_id))).all()
        assert len(values) == 1
        first_revision = values[0]
        assert first_revision.status == "ready"
        assert set(first_revision.source_session_ids) == {str(first.session_id), str(second.session_id)}
        assert set(first_revision.contributor_user_ids) == {"user-a", "user-b"}
        stable_revision_id = first_revision.revision_id
        stable_path = first_revision.graph_artifact_path
        project = await db.get(Project, project_id)
        assert project is not None and project.latest_revision_id == stable_revision_id
    combined = local.load_graph_artifact(first.session_id)
    project_graph = type(combined).model_validate_json(Path(stable_path).read_text(encoding="utf-8"))
    assert {value.canonical_name for value in project_graph.concepts} >= {"方法甲", "方法乙"}

    repeated = await revisions.refresh_project(project_id, principal)
    assert repeated is not None and repeated.revision_id == stable_revision_id

    third = _seed_graph_ready_session("Paper C", "方法丙")
    async with session_factory()() as db:
        db.add(
            Resource(
                organization_id=organization_id,
                project_id=project_id,
                owner_user_id="user-c",
                resource_type="session",
                resource_key=str(third.session_id),
                artifact_path=str(local.session_path(third.session_id)),
            )
        )
        await db.commit()
    second_revision = await revisions.refresh_project(project_id, principal)
    assert second_revision is not None and second_revision.revision_number == 2
    assert second_revision.summary["delta"]["concepts"]["added"] >= 1

    fourth = _seed_graph_ready_session("Paper D", "方法丁")
    async with session_factory()() as db:
        db.add(
            Resource(
                organization_id=organization_id,
                project_id=project_id,
                owner_user_id="user-d",
                resource_type="session",
                resource_key=str(fourth.session_id),
                artifact_path=str(local.session_path(fourth.session_id)),
            )
        )
        await db.commit()
    previous_latest = second_revision.revision_id
    original_builder = revisions._build_revision_graph

    def fail_build(*args, **kwargs):
        raise RuntimeError("simulated project rebuild failure")

    monkeypatch.setattr(revisions, "_build_revision_graph", fail_build)
    with pytest.raises(RuntimeError, match="simulated"):
        await revisions.refresh_project(project_id, principal)
    monkeypatch.setattr(revisions, "_build_revision_graph", original_builder)
    async with session_factory()() as db:
        project = await db.get(Project, project_id)
        assert project is not None and project.latest_revision_id == previous_latest
        failed_count = int(
            await db.scalar(
                select(func.count()).select_from(ProjectRevision).where(
                    ProjectRevision.project_id == project_id,
                    ProjectRevision.status == "failed",
                )
            )
            or 0
        )
        assert failed_count == 1


def test_project_refresh_collapses_updates_is_idempotent_and_preserves_stable_revision(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(settings, "database_url", f"sqlite+aiosqlite:///{tmp_path / 'revisions.db'}")
    monkeypatch.setattr(settings, "database_auto_create", True)
    monkeypatch.setattr(settings, "embed_provider", "hashing")
    monkeypatch.setattr(settings, "embedding_dimensions", 64)
    monkeypatch.setattr(settings, "project_refresh_debounce_seconds", 0.0)
    asyncio.run(dispose_db())
    asyncio.run(_revision_scenario(monkeypatch))
    asyncio.run(dispose_db())
