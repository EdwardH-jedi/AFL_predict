"""
tests/test_fixtures_config.py
------------------------------
Regression coverage for the FixtureOut Pydantic config migration
(class-based ``Config`` -> ``ConfigDict``) and the /fixtures endpoint.
"""

import subprocess
import sys
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

from db.models.matches import Match
from db.models.teams import Team


def test_fixture_out_defines_no_deprecated_config():
    """Importing the route must not emit the class-based config deprecation.

    Runs in a fresh interpreter so the shared, already-imported module (and
    the app's router) are left untouched.
    """
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "import warnings\n"
            "from pydantic.warnings import PydanticDeprecatedSince20\n"
            "warnings.simplefilter('error', PydanticDeprecatedSince20)\n"
            "import api.routes.fixtures as f\n"
            "assert f.FixtureOut.model_config['from_attributes'] is True\n",
        ],
        cwd=Path(__file__).resolve().parents[1],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr


def test_fixture_out_validates_from_attributes():
    from api.routes.fixtures import FixtureOut

    obj = SimpleNamespace(
        id=1,
        season=2026,
        round_number=3,
        round_label="Round 3",
        home_team_id=10,
        away_team_id=20,
        venue="MCG",
        match_time="2026-04-01T19:40:00",
        result=None,
    )
    out = FixtureOut.model_validate(obj)
    assert out.id == 1
    assert out.venue == "MCG"
    assert out.result is None


def test_list_fixtures_endpoint(client, db_session):
    home = Team(name="Collingwood", short_name="COLL")
    away = Team(name="Carlton", short_name="CARL")
    db_session.add_all([home, away])
    db_session.flush()
    db_session.add_all(
        [
            Match(
                season=2026,
                round_number=1,
                round_label="Round 1",
                home_team_id=home.id,
                away_team_id=away.id,
                venue="MCG",
                match_time=datetime(2026, 3, 20, 19, 40),
                result="home",
            ),
            Match(season=2025, round_number=1, home_team_id=away.id, away_team_id=home.id),
        ]
    )
    db_session.commit()

    response = client.get("/fixtures/", params={"season": 2026})
    assert response.status_code == 200
    body = response.json()
    assert len(body) == 1
    assert body[0] == {
        "id": body[0]["id"],
        "season": 2026,
        "round_number": 1,
        "round_label": "Round 1",
        "home_team_id": home.id,
        "away_team_id": away.id,
        "venue": "MCG",
        "match_time": "2026-03-20T19:40:00",
        "result": "home",
    }

    assert len(client.get("/fixtures/").json()) == 2
