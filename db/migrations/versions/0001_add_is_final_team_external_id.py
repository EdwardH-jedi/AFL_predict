"""Add is_final to matches and external_id to teams.

Revision ID: 0001
Revises:
Create Date: 2025-03-20 00:00:00.000000 UTC

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0001"
down_revision: str | None = "0000"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Add is_final column to matches (default False for existing rows)
    with op.batch_alter_table("matches") as batch_op:
        batch_op.add_column(
            sa.Column("is_final", sa.Boolean(), nullable=False, server_default=sa.false())
        )

    # Add external_id column to teams. The unique constraint is created
    # separately with an explicit name — SQLite batch mode requires every
    # constraint to be named, so we cannot use `unique=True` inline.
    with op.batch_alter_table("teams") as batch_op:
        batch_op.add_column(
            sa.Column("external_id", sa.String(50), nullable=True)
        )
        batch_op.create_unique_constraint("uq_teams_external_id", ["external_id"])
        batch_op.create_index("ix_teams_external_id", ["external_id"])


def downgrade() -> None:
    with op.batch_alter_table("teams") as batch_op:
        batch_op.drop_index("ix_teams_external_id")
        batch_op.drop_constraint("uq_teams_external_id", type_="unique")
        batch_op.drop_column("external_id")

    with op.batch_alter_table("matches") as batch_op:
        batch_op.drop_column("is_final")
