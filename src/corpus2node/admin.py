from __future__ import annotations

import argparse
import asyncio
import json

from sqlalchemy import select

from corpus2node.accounts.database import init_db, session_factory
from corpus2node.accounts.migrate_artifacts import migrate_existing_artifacts
from corpus2node.accounts.models import Organization
from corpus2node.accounts.service import create_invitation, create_organization
from corpus2node.config import settings


async def bootstrap_admin(email: str) -> str:
    await init_db()
    async with session_factory()() as db:
        organization = await db.scalar(select(Organization).where(Organization.slug == "platform"))
        if organization is None:
            organization = await create_organization(
                db,
                name="Corpus2Node Platform",
                slug="platform",
                plan_code="team_beta",
            )
        _, token = await create_invitation(
            db,
            organization_id=organization.organization_id,
            email=email,
            role="owner",
            invited_by_user_id=None,
            make_platform_admin=True,
        )
        await db.commit()
    return f"{settings.public_app_url.rstrip('/')}/activate#token={token}"


def parser() -> argparse.ArgumentParser:
    value = argparse.ArgumentParser(description="Corpus2Node account administration")
    commands = value.add_subparsers(dest="command", required=True)
    bootstrap = commands.add_parser("bootstrap-admin", help="Create the first platform-admin activation link")
    bootstrap.add_argument("--email", required=True)
    migrate = commands.add_parser("migrate-artifacts", help="Register existing JSON artifacts without moving them")
    migrate.add_argument("--apply", action="store_true", help="Write metadata rows; default is dry-run")
    migrate.add_argument("--organization-id")
    migrate.add_argument("--organization-name", default="Imported Workspace")
    migrate.add_argument("--owner-email")
    return value


async def _run(args: argparse.Namespace) -> None:
    if args.command == "bootstrap-admin":
        print(await bootstrap_admin(args.email))
        return
    summary = await migrate_existing_artifacts(
        apply=args.apply,
        organization_id=args.organization_id,
        organization_name=args.organization_name,
        owner_email=args.owner_email,
    )
    print(json.dumps(summary.to_dict(), ensure_ascii=False, indent=2))


def main() -> None:
    asyncio.run(_run(parser().parse_args()))


if __name__ == "__main__":
    main()
