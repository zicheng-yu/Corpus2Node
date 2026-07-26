from __future__ import annotations

import argparse
import asyncio
import json

from sqlalchemy import select

from corpus2node.accounts.database import init_db, session_factory
from corpus2node.accounts.migrate_artifacts import migrate_existing_artifacts
from corpus2node.accounts.entitlements import PLAN_CATALOG
from corpus2node.accounts.models import Organization, User
from corpus2node.accounts.security import normalize_email
from corpus2node.accounts.service import create_invitation, create_organization, ensure_personal_organization
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


async def invite_user(email: str, name: str = "", plan_code: str = "free") -> str:
    """Create an activation link backed by a private owner workspace."""
    await init_db()
    clean_email = normalize_email(email)
    if plan_code not in PLAN_CATALOG:
        raise ValueError(f"Unknown plan code: {plan_code}")
    async with session_factory()() as db:
        if await db.scalar(select(User.user_id).where(User.email == clean_email)):
            raise ValueError("An account with this email already exists.")
        label = " ".join(name.split()).strip() or clean_email.split("@", 1)[0]
        organization = await create_organization(
            db,
            name=f"{label} 的资料库",
            plan_code=plan_code,
        )
        _, token = await create_invitation(
            db,
            organization_id=organization.organization_id,
            email=clean_email,
            role="owner",
            invited_by_user_id=None,
        )
        await db.commit()
    return f"{settings.public_app_url.rstrip('/')}/activate#token={token}"


async def migrate_personal_accounts() -> dict[str, int]:
    """Assign every existing user a private workspace without moving artifacts."""
    await init_db()
    assigned = 0
    async with session_factory()() as db:
        users = (await db.scalars(select(User).order_by(User.created_at))).all()
        for user in users:
            had_workspace = bool(user.personal_organization_id)
            await ensure_personal_organization(db, user)
            if not had_workspace:
                assigned += 1
        await db.commit()
    return {"users": len(users), "assigned": assigned}


def parser() -> argparse.ArgumentParser:
    value = argparse.ArgumentParser(description="Corpus2Node account administration")
    commands = value.add_subparsers(dest="command", required=True)
    bootstrap = commands.add_parser("bootstrap-admin", help="Create the first platform-admin activation link")
    bootstrap.add_argument("--email", required=True)
    invite = commands.add_parser("invite-user", help="Create an activation link for a private user account")
    invite.add_argument("--email", required=True)
    invite.add_argument("--name", default="")
    invite.add_argument("--plan", choices=sorted(PLAN_CATALOG), default="free")
    commands.add_parser("migrate-personal-accounts", help="Assign private workspaces to existing accounts")
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
    if args.command == "invite-user":
        print(await invite_user(args.email, args.name, args.plan))
        return
    if args.command == "migrate-personal-accounts":
        print(json.dumps(await migrate_personal_accounts(), ensure_ascii=False))
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
