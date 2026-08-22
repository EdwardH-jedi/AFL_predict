"""Add training_batch_id to model_runs for coherent ensemble assembly.

Revision ID: 0009
Revises: 0008
Create Date: 2026-08-22

Ensemble components were selected independently by best Brier across all
history, so a production ensemble could pair a logistic regression trained in
March with an XGBoost trained in July — different training data, different
feature schema, different code. The blend's weights belong to a configuration,
but its components belonged to nothing in particular.

`training_batch_id` stamps every model produced by one training run with the
same identifier, so components can be required to come from a single coherent
batch.

Additive and nullable: existing rows keep NULL and are simply not eligible for
batch-coherent assembly, which is the correct treatment for runs whose
provenance was never recorded. No data is modified or removed.
"""

import sqlalchemy as sa
from alembic import op

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "model_runs",
        sa.Column("training_batch_id", sa.String(length=64), nullable=True),
    )
    op.create_index(
        "ix_model_runs_training_batch_id", "model_runs", ["training_batch_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_model_runs_training_batch_id", table_name="model_runs")
    op.drop_column("model_runs", "training_batch_id")
