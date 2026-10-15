"""Add match_features table.

Revision ID: 0002
Revises: 0001
Create Date: 2025-03-20 00:01:00.000000 UTC

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "match_features",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("match_id", sa.Integer(), sa.ForeignKey("matches.id"), nullable=False),
        # Denormalised identifiers
        sa.Column("season", sa.SmallInteger(), nullable=False),
        sa.Column("round_number", sa.SmallInteger(), nullable=False),
        sa.Column("home_team_id", sa.Integer(), nullable=False),
        sa.Column("away_team_id", sa.Integer(), nullable=False),
        sa.Column("match_time", sa.DateTime(), nullable=True),
        sa.Column("is_final", sa.Boolean(), nullable=False, server_default=sa.false()),
        # ELO features
        sa.Column("home_elo_pre", sa.Float(), nullable=True),
        sa.Column("away_elo_pre", sa.Float(), nullable=True),
        sa.Column("elo_diff", sa.Float(), nullable=True),
        # Home form
        sa.Column("home_win_rate_l10", sa.Float(), nullable=True),
        sa.Column("home_avg_pts_for_l10", sa.Float(), nullable=True),
        sa.Column("home_avg_pts_against_l10", sa.Float(), nullable=True),
        # Away form
        sa.Column("away_win_rate_l10", sa.Float(), nullable=True),
        sa.Column("away_avg_pts_for_l10", sa.Float(), nullable=True),
        sa.Column("away_avg_pts_against_l10", sa.Float(), nullable=True),
        # Bookmaker features
        sa.Column("bm_home_odds", sa.Float(), nullable=True),
        sa.Column("bm_away_odds", sa.Float(), nullable=True),
        sa.Column("bm_home_implied_prob", sa.Float(), nullable=True),
        sa.Column("bm_away_implied_prob", sa.Float(), nullable=True),
        sa.Column("bm_overround", sa.Float(), nullable=True),
        # Rest / travel
        sa.Column("home_rest_days", sa.Integer(), nullable=True),
        sa.Column("away_rest_days", sa.Integer(), nullable=True),
        # Venue
        sa.Column("venue", sa.String(100), nullable=True),
        # Target
        sa.Column("home_win", sa.Integer(), nullable=True),
        # Metadata
        sa.Column("feature_computed_at", sa.DateTime(), server_default=sa.func.now()),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
        sa.UniqueConstraint("match_id", name="uq_match_features_match_id"),
    )
    op.create_index("ix_match_features_match_id", "match_features", ["match_id"])
    op.create_index("ix_match_features_season", "match_features", ["season"])


def downgrade() -> None:
    op.drop_index("ix_match_features_season", table_name="match_features")
    op.drop_index("ix_match_features_match_id", table_name="match_features")
    op.drop_table("match_features")
