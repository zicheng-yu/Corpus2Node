"""User and invitation product persona.

Revision ID: 20260726_0003
Revises: 20260715_0002
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "20260726_0003"
down_revision = "20260715_0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("users") as batch:
        batch.add_column(sa.Column("persona", sa.String(20), nullable=False, server_default="operator"))
    with op.batch_alter_table("invitations") as batch:
        batch.add_column(sa.Column("persona", sa.String(20), nullable=False, server_default="operator"))


def downgrade() -> None:
    with op.batch_alter_table("invitations") as batch:
        batch.drop_column("persona")
    with op.batch_alter_table("users") as batch:
        batch.drop_column("persona")
