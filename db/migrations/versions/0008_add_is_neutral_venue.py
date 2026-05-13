"""0008_add_is_neutral_venue

Adds is_neutral_venue boolean column to the matches table.

A neutral venue match is one where the API-designated home team is NOT
playing at their registered home ground (e.g. Gather Round, interstate
neutral fixtures, MCG finals for non-Melbourne teams).

This flag is set at ingestion time by afl_transformer using the
TEAM_HOME_VENUES mapping in collectors/venue_rules.py.

Revision ID: 0008
Revises: 0007
"""

import sqlalchemy as sa
from alembic import op

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "matches",
        sa.Column(
            "is_neutral_venue",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )

    # Back-fill existing rows using known neutral venue strings.
    # Adelaide Oval, Barossa Park, Norwood Oval are Gather Round venues.
    # York Park, Traeger Park, Hands Oval, Marrara Oval, Manuka Oval,
    # Bellerive Oval are interstate venues used as home grounds by no AFL team.
    op.execute("""
        UPDATE matches SET is_neutral_venue = 1
        WHERE venue IN (
            'Barossa Park',
            'Norwood Oval',
            'York Park',
            'Traeger Park',
            'Hands Oval',
            'Marrara Oval',
            'Manuka Oval',
            'Bellerive Oval'
        )
    """)

    # Adelaide Oval is home to Adelaide and Port Adelaide.
    # Mark it neutral for all other teams.
    op.execute("""
        UPDATE matches SET is_neutral_venue = 1
        WHERE venue = 'Adelaide Oval'
        AND home_team_id NOT IN (
            SELECT id FROM teams WHERE name IN ('Adelaide', 'Port Adelaide')
        )
    """)


def downgrade() -> None:
    op.drop_column("matches", "is_neutral_venue")
