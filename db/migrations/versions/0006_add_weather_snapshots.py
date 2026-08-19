"""Add weather_snapshots table.

Revision ID: 0006
Revises: 0005
Create Date: 2026-04-07

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "weather_snapshots",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "match_id",
            sa.Integer(),
            sa.ForeignKey("matches.id"),
            unique=True,
            nullable=False,
        ),
        sa.Column("venue_name", sa.String(100), nullable=True),
        sa.Column("latitude", sa.Float(), nullable=True),
        sa.Column("longitude", sa.Float(), nullable=True),
        sa.Column("temperature_c", sa.Float(), nullable=True),
        sa.Column("apparent_temp_c", sa.Float(), nullable=True),
        sa.Column("precipitation_mm", sa.Float(), nullable=True),
        sa.Column("wind_speed_kmh", sa.Float(), nullable=True),
        sa.Column("wind_gusts_kmh", sa.Float(), nullable=True),
        sa.Column("wind_direction_deg", sa.Float(), nullable=True),
        sa.Column("cloud_cover_pct", sa.Float(), nullable=True),
        sa.Column("weather_code", sa.Integer(), nullable=True),
        sa.Column("is_raining", sa.Integer(), nullable=True),
        sa.Column("is_high_wind", sa.Integer(), nullable=True),
        sa.Column("is_extreme_heat", sa.Integer(), nullable=True),
        sa.Column("source_type", sa.String(20), nullable=False, server_default="forecast"),
        sa.Column("fetched_at", sa.DateTime(), server_default=sa.func.now()),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
    )
    op.create_index("ix_weather_snapshots_match_id", "weather_snapshots", ["match_id"])


def downgrade() -> None:
    op.drop_index("ix_weather_snapshots_match_id", table_name="weather_snapshots")
    op.drop_table("weather_snapshots")
