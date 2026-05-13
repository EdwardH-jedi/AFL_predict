"""Create initial schema (teams, matches, predictions, ...).

Revision ID: 0000
Revises:
Create Date: 2026-05-13 00:00:00.000000 UTC

Historically the base schema was bootstrapped with
``Base.metadata.create_all`` (``make db-init``) and individual migrations
(0001+) only described the deltas, which broke fresh installs:
``alembic upgrade head`` against an empty database failed at 0001
because that migration assumed ``matches`` and ``teams`` already existed.

This migration restores the missing base layer so that
``alembic upgrade head`` works against an empty database. It captures
the schema exactly as it existed BEFORE migration 0001 — later
migrations 0001..N evolve this schema toward the current ORM model.

Existing databases already at a later head (e.g. 0008) are NOT affected:
Alembic only walks forward from the revision stored in ``alembic_version``.
Adding a new ancestor revision does not retroactively re-run earlier
migrations on databases that have already advanced.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0000"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # ---------------- teams ----------------
    # external_id column is added later by migration 0001.
    op.create_table(
        "teams",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("name", sa.String(100), nullable=False, unique=True),
        sa.Column("short_name", sa.String(10), nullable=False),
        sa.Column("state", sa.String(50), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=True),
    )
    op.create_index("ix_teams_name", "teams", ["name"])

    # ---------------- matches ----------------
    # is_final column is added later by migration 0001.
    # is_neutral_venue column is added later by migration 0008.
    op.create_table(
        "matches",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("season", sa.SmallInteger(), nullable=False),
        sa.Column("round_number", sa.SmallInteger(), nullable=False),
        sa.Column("round_label", sa.String(50), nullable=True),
        sa.Column("home_team_id", sa.Integer(), sa.ForeignKey("teams.id"), nullable=False),
        sa.Column("away_team_id", sa.Integer(), sa.ForeignKey("teams.id"), nullable=False),
        sa.Column("match_time", sa.DateTime(), nullable=True),
        sa.Column("venue", sa.String(100), nullable=True),
        sa.Column("home_score", sa.Integer(), nullable=True),
        sa.Column("away_score", sa.Integer(), nullable=True),
        sa.Column("result", sa.String(10), nullable=True),
        sa.Column("external_id", sa.String(100), nullable=True, unique=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(),
            server_default=sa.func.now(),
            onupdate=sa.func.now(),
            nullable=True,
        ),
    )
    op.create_index("ix_matches_season", "matches", ["season"])
    op.create_index("ix_matches_match_time", "matches", ["match_time"])

    # ---------------- model_runs ----------------
    op.create_table(
        "model_runs",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("model_name", sa.String(100), nullable=False),
        sa.Column("model_version", sa.String(50), nullable=False),
        sa.Column("train_from_season", sa.Integer(), nullable=True),
        sa.Column("train_to_season", sa.Integer(), nullable=True),
        sa.Column("brier_score", sa.Float(), nullable=True),
        sa.Column("log_loss", sa.Float(), nullable=True),
        sa.Column("accuracy", sa.Float(), nullable=True),
        sa.Column("artifact_path", sa.String(500), nullable=True),
        sa.Column("metadata_json", sa.Text(), nullable=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="pending"),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=True),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
    )
    op.create_index("ix_model_runs_model_name", "model_runs", ["model_name"])

    # ---------------- predictions ----------------
    op.create_table(
        "predictions",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("match_id", sa.Integer(), sa.ForeignKey("matches.id"), nullable=False),
        sa.Column("model_run_id", sa.Integer(), sa.ForeignKey("model_runs.id"), nullable=False),
        sa.Column("home_win_prob", sa.Float(), nullable=False),
        sa.Column("away_win_prob", sa.Float(), nullable=False),
        sa.Column("home_edge", sa.Float(), nullable=True),
        sa.Column("away_edge", sa.Float(), nullable=True),
        sa.Column("kelly_home", sa.Float(), nullable=True),
        sa.Column("kelly_away", sa.Float(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=True),
    )
    op.create_index("ix_predictions_match_id", "predictions", ["match_id"])
    op.create_index("ix_predictions_model_run_id", "predictions", ["model_run_id"])

    # ---------------- recommendations ----------------
    op.create_table(
        "recommendations",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "prediction_id",
            sa.Integer(),
            sa.ForeignKey("predictions.id"),
            nullable=False,
            unique=True,
        ),
        sa.Column("side", sa.String(10), nullable=False),
        sa.Column("recommended_odds", sa.Float(), nullable=False),
        sa.Column("stake_fraction", sa.Float(), nullable=False),
        sa.Column("stake_dollars", sa.Float(), nullable=True),
        sa.Column("paper_trade", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("status", sa.String(20), nullable=False, server_default="pending"),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=True),
    )
    op.create_index("ix_recommendations_prediction_id", "recommendations", ["prediction_id"])

    # ---------------- bet_outcomes ----------------
    # Migration 0007 makes recommendation_id nullable and adds many extra columns
    # for live-TAB tracking. Here we recreate the pre-0007 shape.
    op.create_table(
        "bet_outcomes",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "recommendation_id",
            sa.Integer(),
            sa.ForeignKey("recommendations.id"),
            nullable=False,
            unique=True,
        ),
        sa.Column("won", sa.Boolean(), nullable=True),
        sa.Column("profit_loss_units", sa.Float(), nullable=True),
        sa.Column("profit_loss_dollars", sa.Float(), nullable=True),
        sa.Column("settled_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=True),
    )
    op.create_index("ix_bet_outcomes_recommendation_id", "bet_outcomes", ["recommendation_id"])

    # ---------------- bankroll_logs ----------------
    # log_type column is added later by migration 0007.
    op.create_table(
        "bankroll_logs",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("event_type", sa.String(30), nullable=False),
        sa.Column("balance_after", sa.Float(), nullable=False),
        sa.Column("amount", sa.Float(), nullable=False),
        sa.Column("recommendation_id", sa.Integer(), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=True),
    )

    # ---------------- odds_snapshots ----------------
    op.create_table(
        "odds_snapshots",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("match_id", sa.Integer(), sa.ForeignKey("matches.id"), nullable=False),
        sa.Column("bookmaker", sa.String(50), nullable=False, server_default="TAB"),
        sa.Column("home_odds", sa.Float(), nullable=True),
        sa.Column("away_odds", sa.Float(), nullable=True),
        sa.Column("home_implied_prob", sa.Float(), nullable=True),
        sa.Column("away_implied_prob", sa.Float(), nullable=True),
        sa.Column("overround", sa.Float(), nullable=True),
        sa.Column("snapshot_time", sa.DateTime(), nullable=False),
        sa.Column("snapshot_type", sa.String(20), nullable=False, server_default="scheduled"),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=True),
    )
    op.create_index("ix_odds_snapshots_match_id", "odds_snapshots", ["match_id"])
    op.create_index("ix_odds_snapshots_snapshot_time", "odds_snapshots", ["snapshot_time"])

    # ---------------- pipeline_runs ----------------
    # daily_run_id and retry_count columns are added later by migration 0003.
    op.create_table(
        "pipeline_runs",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("job_name", sa.String(100), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="pending"),
        sa.Column("started_at", sa.DateTime(), server_default=sa.func.now(), nullable=True),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.Column("duration_seconds", sa.Float(), nullable=True),
        sa.Column("records_processed", sa.Integer(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
    )
    op.create_index("ix_pipeline_runs_job_name", "pipeline_runs", ["job_name"])


def downgrade() -> None:
    op.drop_index("ix_pipeline_runs_job_name", table_name="pipeline_runs")
    op.drop_table("pipeline_runs")

    op.drop_index("ix_odds_snapshots_snapshot_time", table_name="odds_snapshots")
    op.drop_index("ix_odds_snapshots_match_id", table_name="odds_snapshots")
    op.drop_table("odds_snapshots")

    op.drop_table("bankroll_logs")

    op.drop_index("ix_bet_outcomes_recommendation_id", table_name="bet_outcomes")
    op.drop_table("bet_outcomes")

    op.drop_index("ix_recommendations_prediction_id", table_name="recommendations")
    op.drop_table("recommendations")

    op.drop_index("ix_predictions_model_run_id", table_name="predictions")
    op.drop_index("ix_predictions_match_id", table_name="predictions")
    op.drop_table("predictions")

    op.drop_index("ix_model_runs_model_name", table_name="model_runs")
    op.drop_table("model_runs")

    op.drop_index("ix_matches_match_time", table_name="matches")
    op.drop_index("ix_matches_season", table_name="matches")
    op.drop_table("matches")

    op.drop_index("ix_teams_name", table_name="teams")
    op.drop_table("teams")
