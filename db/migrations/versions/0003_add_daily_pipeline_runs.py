"""0003_add_daily_pipeline_runs

Adds:
  - daily_pipeline_runs table (top-level per-day pipeline record)
  - Extends pipeline_runs with: daily_run_id FK, retry_count column
  - Updates pipeline_runs.status to support new states:
    pending, partial_failure, skipped (previously: running, completed, failed)

Revision ID: 0003
Revises: 0002
"""

import sqlalchemy as sa
from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Create daily_pipeline_runs table
    op.create_table(
        "daily_pipeline_runs",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("run_uuid", sa.String(36), nullable=False, index=True),
        sa.Column("run_date", sa.Date(), nullable=False, index=True),
        sa.Column("triggered_by", sa.String(20), nullable=False, default="manual"),
        sa.Column("status", sa.String(20), nullable=False, default="pending"),
        sa.Column("started_at", sa.DateTime(), server_default=sa.func.now()),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.Column("duration_seconds", sa.Float(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
    )

    # Add daily_run_id FK and retry_count to pipeline_runs. SQLite cannot
    # ALTER constraints in place, so the FK column must be added via batch
    # mode (copy-and-move). Indexes/FK names are explicit because batch mode
    # requires every constraint and index to be named on SQLite.
    with op.batch_alter_table("pipeline_runs") as batch_op:
        batch_op.add_column(
            sa.Column("daily_run_id", sa.Integer(), nullable=True),
        )
        batch_op.create_foreign_key(
            "fk_pipeline_runs_daily_run_id_daily_pipeline_runs",
            "daily_pipeline_runs",
            ["daily_run_id"],
            ["id"],
        )
        batch_op.create_index(
            "ix_pipeline_runs_daily_run_id", ["daily_run_id"]
        )
        batch_op.add_column(
            sa.Column("retry_count", sa.Integer(), nullable=False, server_default="0"),
        )

    # Note: SQLite does not support ALTER COLUMN — status column length/values
    # are validated at the application layer, not enforced by the DB.


def downgrade() -> None:
    with op.batch_alter_table("pipeline_runs") as batch_op:
        batch_op.drop_column("retry_count")
        batch_op.drop_index("ix_pipeline_runs_daily_run_id")
        batch_op.drop_constraint(
            "fk_pipeline_runs_daily_run_id_daily_pipeline_runs", type_="foreignkey"
        )
        batch_op.drop_column("daily_run_id")
    op.drop_table("daily_pipeline_runs")
