from __future__ import annotations

import asyncio
import json

from sqlalchemy import func, select

from corpus2node.accounts.database import dispose_db, init_db, session_factory
from corpus2node.accounts.migrate_artifacts import inventory, migrate_existing_artifacts
from corpus2node.accounts.models import Project, Resource, User
from corpus2node.accounts.security import hash_password
from corpus2node.config import settings
from corpus2node.core.types import CourseSession, SourceFile, SourceKind
from corpus2node.storage import local


async def _seed_admin() -> None:
    await init_db()
    async with session_factory()() as db:
        db.add(
            User(
                email="migration-owner@example.com",
                display_name="Migration Owner",
                password_hash=hash_password("migration-password-123"),
                is_platform_admin=True,
            )
        )
        await db.commit()


async def _counts() -> tuple[int, int]:
    await init_db()
    async with session_factory()() as db:
        projects = int(await db.scalar(select(func.count()).select_from(Project)) or 0)
        resources = int(await db.scalar(select(func.count()).select_from(Resource)) or 0)
        return projects, resources


def test_load_session_relocates_copied_upload_without_rewriting_artifact(tmp_path, monkeypatch):
    artifacts = tmp_path / "artifacts"
    monkeypatch.setattr(settings, "local_storage_path", str(artifacts))
    session = CourseSession(
        course_title="Portable Topic",
        lecture_title="Copied Paper",
        source_files=[
            SourceFile(
                kind=SourceKind.document,
                filename="paper.md",
                content_type="text/markdown",
                storage_path="/old/machine/artifacts/session/uploads/paper.md",
                size_bytes=8,
            )
        ],
    )
    copied = local.upload_dir(session.session_id) / "paper.md"
    copied.write_text("evidence", encoding="utf-8")
    artifact = local.save_session(session)
    before = artifact.read_bytes()

    loaded = local.load_session(session.session_id)

    assert loaded.source_files[0].storage_path == str(copied)
    assert artifact.read_bytes() == before
    assert json.loads(before)["source_files"][0]["storage_path"].startswith("/old/machine/")


def test_artifact_migration_is_dry_run_first_idempotent_and_non_destructive(tmp_path, monkeypatch):
    artifacts = tmp_path / "artifacts"
    monkeypatch.setattr(settings, "local_storage_path", str(artifacts))
    monkeypatch.setattr(settings, "database_url", f"sqlite+aiosqlite:///{artifacts / 'custom-metadata.db'}")
    monkeypatch.setattr(settings, "database_auto_create", True)
    asyncio.run(dispose_db())
    asyncio.run(_seed_admin())
    (artifacts / ".DS_Store").write_bytes(b"host metadata")

    upload = artifacts / "seed-paper.md"
    local.write_text_atomic(upload, "# Evidence\n\nGrounded text.")
    for title in ("Paper A", "Paper B"):
        session = CourseSession(
            course_title="Imported Topic",
            lecture_title=title,
            source_files=[
                SourceFile(
                    kind=SourceKind.document,
                    filename=upload.name,
                    content_type="text/markdown",
                    storage_path=str(upload),
                    size_bytes=upload.stat().st_size,
                )
            ],
        )
        local.save_session(session)

    _, before_hash, before_bytes = inventory()
    dry_run = asyncio.run(migrate_existing_artifacts())
    assert dry_run.dry_run is True
    assert dry_run.artifact_file_count == 3
    assert dry_run.sessions == 2
    assert dry_run.projects == 1

    applied = asyncio.run(
        migrate_existing_artifacts(apply=True, owner_email="migration-owner@example.com")
    )
    assert applied.dry_run is False
    assert applied.resources_created == 4
    assert asyncio.run(_counts()) == (1, 4)
    _, after_hash, after_bytes = inventory()
    assert (after_hash, after_bytes) == (before_hash, before_bytes)
    assert upload.read_text(encoding="utf-8").startswith("# Evidence")

    repeated = asyncio.run(
        migrate_existing_artifacts(
            apply=True,
            organization_id=applied.organization_id,
            owner_email="migration-owner@example.com",
        )
    )
    assert repeated.resources_created == 0
    assert asyncio.run(_counts()) == (1, 4)
    asyncio.run(dispose_db())
