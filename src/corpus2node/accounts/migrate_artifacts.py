from __future__ import annotations

import hashlib
from dataclasses import asdict, dataclass
from pathlib import Path
from sqlalchemy import select

from corpus2node.accounts.database import init_db, session_factory
from corpus2node.accounts.models import Membership, Organization, Project, Resource, User
from corpus2node.accounts.service import AccountError, create_organization
from corpus2node.config import settings
from corpus2node.storage import local


@dataclass
class MigrationSummary:
    dry_run: bool
    artifact_file_count: int
    artifact_bytes: int
    artifact_sha256: str
    sessions: int = 0
    projects: int = 0
    sources: int = 0
    graphs: int = 0
    scientific_reports: int = 0
    discovery_reports: int = 0
    private_artifacts: int = 0
    resources_created: int = 0
    organization_id: str | None = None

    def to_dict(self) -> dict:
        return asdict(self)


def inventory() -> tuple[list[Path], str, int]:
    root = Path(settings.local_storage_path)
    if not root.exists():
        return [], hashlib.sha256(b"").hexdigest(), 0
    database_path = _sqlite_database_path()
    files = sorted(
        path
        for path in root.rglob("*")
        if path.is_file()
        and path.name != ".DS_Store"
        and not path.name.startswith("._")
        and not path.name.startswith("metadata.db")
        and not path.name.startswith(".metadata.db")
        and not (
            database_path is not None
            and (path == database_path or path.name.startswith(f"{database_path.name}-"))
        )
    )
    digest = hashlib.sha256()
    total_bytes = 0
    for path in files:
        relative = str(path.relative_to(root)).encode("utf-8")
        digest.update(len(relative).to_bytes(8, "big"))
        digest.update(relative)
        with path.open("rb") as handle:
            while block := handle.read(1024 * 1024):
                total_bytes += len(block)
                digest.update(block)
    return files, digest.hexdigest(), total_bytes


def _sqlite_database_path() -> Path | None:
    prefix = "sqlite+aiosqlite:///"
    if not settings.database_url.startswith(prefix):
        return None
    return Path(settings.database_url.removeprefix(prefix)).resolve()


async def migrate_existing_artifacts(
    *,
    apply: bool = False,
    organization_id: str | None = None,
    organization_name: str = "Imported Workspace",
    owner_email: str | None = None,
) -> MigrationSummary:
    files, digest, total_bytes = inventory()
    sessions = []
    for session_id in local.list_session_ids():
        try:
            sessions.append(local.load_session(session_id))
        except (FileNotFoundError, ValueError):
            continue
    summary = MigrationSummary(
        dry_run=not apply,
        artifact_file_count=len(files),
        artifact_bytes=total_bytes,
        artifact_sha256=digest,
        sessions=len(sessions),
        projects=len({value.course_title for value in sessions}),
        sources=sum(len(value.source_files) for value in sessions),
        graphs=sum(local.graph_path(value.session_id).is_file() for value in sessions),
        scientific_reports=len(local.list_scientific_reports()),
        discovery_reports=len(local.list_discovery_reports()),
        private_artifacts=sum(
            path.is_file()
            for session in sessions
            for path in (local.notes_path(session.session_id), local.test_path(session.session_id), local.chat_path(session.session_id))
        ),
    )
    if not apply:
        return summary

    await init_db()
    async with session_factory()() as db:
        owner = await _migration_owner(db, owner_email)
        organization = await db.get(Organization, organization_id) if organization_id else None
        if organization_id and organization is None:
            raise AccountError("Target organization not found.")
        if organization is None:
            organization = await create_organization(db, name=organization_name, plan_code="team_beta")
        summary.organization_id = organization.organization_id
        membership = await db.get(Membership, (organization.organization_id, owner.user_id))
        if membership is None:
            db.add(Membership(organization_id=organization.organization_id, user_id=owner.user_id, role="owner"))
        await db.flush()

        projects: dict[str, Project] = {}
        for title in sorted({value.course_title for value in sessions}):
            project = await db.scalar(
                select(Project).where(
                    Project.organization_id == organization.organization_id,
                    Project.name == title,
                )
            )
            if project is None:
                project = Project(
                    organization_id=organization.organization_id,
                    name=title,
                    kind="general",
                    created_by_user_id=owner.user_id,
                )
                db.add(project)
                await db.flush()
            projects[title] = project

        session_projects: dict[str, str] = {}
        for session in sessions:
            project = projects[session.course_title]
            session_projects[str(session.session_id)] = project.project_id
            summary.resources_created += await _ensure_resource(
                db,
                organization_id=organization.organization_id,
                project_id=project.project_id,
                owner_user_id=owner.user_id,
                resource_type="session",
                resource_key=str(session.session_id),
                artifact_path=str(local.session_path(session.session_id)),
            )
            for source in session.source_files:
                summary.resources_created += await _ensure_resource(
                    db,
                    organization_id=organization.organization_id,
                    project_id=project.project_id,
                    owner_user_id=owner.user_id,
                    resource_type="source",
                    resource_key=str(source.source_id),
                    artifact_path=source.storage_path,
                    size_bytes=source.size_bytes,
                )
            if local.graph_path(session.session_id).is_file():
                summary.resources_created += await _ensure_resource(
                    db,
                    organization_id=organization.organization_id,
                    project_id=project.project_id,
                    owner_user_id=None,
                    resource_type="session_graph",
                    resource_key=str(session.session_id),
                    artifact_path=str(local.graph_path(session.session_id)),
                )
            for resource_type, path in (
                ("note", local.notes_path(session.session_id)),
                ("test", local.test_path(session.session_id)),
                ("chat", local.chat_path(session.session_id)),
            ):
                if path.is_file():
                    summary.resources_created += await _ensure_resource(
                        db,
                        organization_id=organization.organization_id,
                        project_id=project.project_id,
                        owner_user_id=owner.user_id,
                        resource_type=resource_type,
                        resource_key=f"{session.session_id}:{owner.user_id}",
                        artifact_path=str(path),
                    )

        for report in local.list_scientific_reports():
            project_ids = {session_projects.get(str(value)) for value in report.session_ids}
            project_ids.discard(None)
            project_id = next(iter(project_ids)) if len(project_ids) == 1 else None
            summary.resources_created += await _ensure_resource(
                db,
                organization_id=organization.organization_id,
                project_id=project_id,
                owner_user_id=None,
                resource_type="scientific_report",
                resource_key=report.report_id,
                artifact_path=str(local.scientific_path(report.report_id)),
            )
        for report in local.list_discovery_reports():
            project_ids = {session_projects.get(str(value)) for value in report.session_ids}
            project_ids.discard(None)
            project_id = next(iter(project_ids)) if len(project_ids) == 1 else None
            summary.resources_created += await _ensure_resource(
                db,
                organization_id=organization.organization_id,
                project_id=project_id,
                owner_user_id=None,
                resource_type="discovery_report",
                resource_key=report.discovery_id,
                artifact_path=str(local.discovery_path(report.discovery_id)),
            )
        await db.commit()
    _, after_digest, after_bytes = inventory()
    if after_digest != summary.artifact_sha256 or after_bytes != summary.artifact_bytes:
        raise RuntimeError("Artifact inventory changed during metadata migration; no source files were intentionally moved.")
    return summary


async def _migration_owner(db, owner_email: str | None) -> User:
    if owner_email:
        owner = await db.scalar(select(User).where(User.email == owner_email.strip().casefold()))
    else:
        owner = await db.scalar(select(User).where(User.is_platform_admin.is_(True)).order_by(User.created_at))
    if owner is None:
        raise AccountError("Create or activate a platform administrator before applying artifact migration.")
    return owner


async def _ensure_resource(
    db,
    *,
    organization_id: str,
    project_id: str | None,
    owner_user_id: str | None,
    resource_type: str,
    resource_key: str,
    artifact_path: str,
    size_bytes: int = 0,
) -> int:
    existing = await db.scalar(
        select(Resource.resource_id).where(
            Resource.resource_type == resource_type,
            Resource.resource_key == resource_key,
        )
    )
    if existing:
        return 0
    db.add(
        Resource(
            organization_id=organization_id,
            project_id=project_id,
            owner_user_id=owner_user_id,
            resource_type=resource_type,
            resource_key=resource_key,
            artifact_path=artifact_path,
            size_bytes=size_bytes,
        )
    )
    await db.flush()
    return 1
