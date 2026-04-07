"""Add player_lineups and player_stats tables.

Revision ID: 0005
Revises: 0004
Create Date: 2026-04-07

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0005"
down_revision: Union[str, None] = "0003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "player_lineups",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("match_id", sa.Integer(), sa.ForeignKey("matches.id"), nullable=False),
        sa.Column("team_id", sa.Integer(), sa.ForeignKey("teams.id"), nullable=False),
        sa.Column("players_listed", sa.SmallInteger(), nullable=True),
        sa.Column("players_absent", sa.SmallInteger(), nullable=True),
        sa.Column("key_players_absent", sa.SmallInteger(), nullable=True),
        sa.Column("availability_index", sa.Float(), nullable=True),
        sa.Column("announced_at", sa.DateTime(), nullable=True),
        sa.Column("source", sa.String(30), nullable=False, server_default="afltables"),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
    )
    op.create_index("ix_player_lineups_match_id", "player_lineups", ["match_id"])
    op.create_index("ix_player_lineups_team_id", "player_lineups", ["team_id"])

    op.create_table(
        "player_stats",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("match_id", sa.Integer(), sa.ForeignKey("matches.id"), nullable=False),
        sa.Column("team_id", sa.Integer(), sa.ForeignKey("teams.id"), nullable=False),
        sa.Column("player_external_id", sa.String(50), nullable=False),
        sa.Column("player_name", sa.String(100), nullable=False),
        sa.Column("disposals", sa.SmallInteger(), nullable=True),
        sa.Column("kicks", sa.SmallInteger(), nullable=True),
        sa.Column("handballs", sa.SmallInteger(), nullable=True),
        sa.Column("goals", sa.SmallInteger(), nullable=True),
        sa.Column("behinds", sa.SmallInteger(), nullable=True),
        sa.Column("contribution_score", sa.Float(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
    )
    op.create_index("ix_player_stats_match_id", "player_stats", ["match_id"])
    op.create_index("ix_player_stats_player_id", "player_stats", ["player_external_id"])


def downgrade() -> None:
    op.drop_index("ix_player_stats_player_id", table_name="player_stats")
    op.drop_index("ix_player_stats_match_id", table_name="player_stats")
    op.drop_table("player_stats")

    op.drop_index("ix_player_lineups_team_id", table_name="player_lineups")
    op.drop_index("ix_player_lineups_match_id", table_name="player_lineups")
    op.drop_table("player_lineups")
