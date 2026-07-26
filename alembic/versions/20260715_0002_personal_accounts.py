"""Personal account workspaces.

Revision ID: 20260715_0002
Revises: 20260714_0001
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "20260715_0002"
down_revision = "20260714_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("users") as batch:
        batch.add_column(sa.Column("personal_organization_id", sa.String(36), nullable=True))
    with op.batch_alter_table("organizations") as batch:
        batch.add_column(sa.Column("personal_owner_user_id", sa.String(36), nullable=True))
        batch.create_unique_constraint("uq_organization_personal_owner", ["personal_owner_user_id"])


def downgrade() -> None:
    with op.batch_alter_table("organizations") as batch:
        batch.drop_constraint("uq_organization_personal_owner", type_="unique")
        batch.drop_column("personal_owner_user_id")
    with op.batch_alter_table("users") as batch:
        batch.drop_column("personal_organization_id")
