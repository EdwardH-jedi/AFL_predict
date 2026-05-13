"""0007_tab_tracking

Extends bet_outcomes and bankroll_logs for live TAB bet tracking and CLV.

Changes to bet_outcomes:
  - recommendation_id: nullable=True (TAB bets may have no matching recommendation)
  - Add: match_id, bet_side, bet_source, recommended_odds, actual_tab_odds,
         odds_slippage, stake_fraction, stake_amount_aud, payout_amount_aud,
         placed_at, closing_odds, closing_implied_prob, clv, clv_computed_at

Changes to bankroll_logs:
  - Add: log_type ('paper' | 'live', default 'paper')

Revision ID: 0007
Revises: 0006
"""

import sqlalchemy as sa
from alembic import op

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ----------------------------------------------------------------
    # bet_outcomes — use batch_alter_table for SQLite compatibility
    # ----------------------------------------------------------------
    with op.batch_alter_table("bet_outcomes", recreate="always") as batch_op:
        # Make recommendation_id nullable (was NOT NULL)
        batch_op.alter_column(
            "recommendation_id",
            existing_type=sa.Integer(),
            nullable=True,
        )
        batch_op.add_column(sa.Column("match_id", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("bet_side", sa.String(10), nullable=True))
        batch_op.add_column(
            sa.Column("bet_source", sa.String(20), nullable=False, server_default="paper")
        )
        batch_op.add_column(sa.Column("recommended_odds", sa.Float(), nullable=True))
        batch_op.add_column(sa.Column("actual_tab_odds", sa.Float(), nullable=True))
        batch_op.add_column(sa.Column("odds_slippage", sa.Float(), nullable=True))
        batch_op.add_column(sa.Column("stake_fraction", sa.Float(), nullable=True))
        batch_op.add_column(sa.Column("stake_amount_aud", sa.Float(), nullable=True))
        batch_op.add_column(sa.Column("payout_amount_aud", sa.Float(), nullable=True))
        batch_op.add_column(sa.Column("placed_at", sa.DateTime(), nullable=True))
        batch_op.add_column(sa.Column("closing_odds", sa.Float(), nullable=True))
        batch_op.add_column(sa.Column("closing_implied_prob", sa.Float(), nullable=True))
        batch_op.add_column(sa.Column("clv", sa.Float(), nullable=True))
        batch_op.add_column(sa.Column("clv_computed_at", sa.DateTime(), nullable=True))

    # ----------------------------------------------------------------
    # bankroll_logs — simple add_column (no constraint changes)
    # ----------------------------------------------------------------
    op.add_column(
        "bankroll_logs",
        sa.Column("log_type", sa.String(10), nullable=False, server_default="paper"),
    )


def downgrade() -> None:
    op.drop_column("bankroll_logs", "log_type")

    with op.batch_alter_table("bet_outcomes", recreate="always") as batch_op:
        batch_op.drop_column("clv_computed_at")
        batch_op.drop_column("clv")
        batch_op.drop_column("closing_implied_prob")
        batch_op.drop_column("closing_odds")
        batch_op.drop_column("placed_at")
        batch_op.drop_column("payout_amount_aud")
        batch_op.drop_column("stake_amount_aud")
        batch_op.drop_column("stake_fraction")
        batch_op.drop_column("odds_slippage")
        batch_op.drop_column("actual_tab_odds")
        batch_op.drop_column("recommended_odds")
        batch_op.drop_column("bet_source")
        batch_op.drop_column("bet_side")
        batch_op.drop_column("match_id")
        batch_op.alter_column(
            "recommendation_id",
            existing_type=sa.Integer(),
            nullable=False,
        )
