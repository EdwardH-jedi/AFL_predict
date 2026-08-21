"""
tests/test_dashboard_edge_semantics.py
---------------------------------------
Regression coverage for the side-alignment invariant in the dashboard.

    a probability is only ever compared against its OWN side's price
    home probability <-> home price,  away probability <-> away price

This bug escaped self-review twice, in two different disguises:

  1. Every row was priced with `tab_odds`, which is the HOME price by
     definition, so an away pick was scored against the home price.
  2. The "fix" switched to `bet_odds` — the price of the *recommended bet*.
     That is a different thing again: the model can favour the away side while
     the value sits on the home side, so the pick's probability was still being
     paired with the other team's price.

Both fabricated an edge. The observed case was Essendon v Carlton: the pick
(Carlton, p=0.5715) shown against Essendon's 3.846, producing +31.15% where the
truthful figure for that pick is -16.87%.

These tests execute the real `_gamesToPicks` from static/quant-dashboard/data.jsx
under node, so they cover the shipped code rather than a restatement of it.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
DATA_JSX = REPO_ROOT / "static" / "quant-dashboard" / "data.jsx"

pytestmark = pytest.mark.skipif(
    shutil.which("node") is None, reason="node is required to exercise the dashboard transform"
)

# Asymmetric prices on purpose: if the two sides were ever swapped, no rounding
# or coincidence could hide it.
HOME_ODDS = 1.40
AWAY_ODDS = 3.80

_DRIVER = r"""
const fs = require('fs');
const vm = require('vm');

// data.jsx is plain JS (no JSX) written for a browser. Give it the globals it
// touches at load time, then pull the transform out of the sandbox.
const sandbox = {
  window: { AFLData: {}, AFLLive: {}, addEventListener() {}, dispatchEvent() {} },
  document: { addEventListener() {} },
  console,
  fetch: () => Promise.reject(new Error('network disabled in tests')),
  setTimeout, clearTimeout,
  // Swallowed on purpose: the module schedules its predictions.json fetch
  // through this at load time, and these tests exercise the pure transform.
  requestAnimationFrame: () => {},
};
sandbox.globalThis = sandbox;
vm.createContext(sandbox);
vm.runInContext(fs.readFileSync(process.argv[2], 'utf8'), sandbox, {filename: 'data.jsx'});

const games = JSON.parse(process.argv[3]);
const picks = sandbox._gamesToPicks(games);
process.stdout.write(JSON.stringify(picks.map(p => ({
  pick: p.pick && p.pick.name,
  pred: p.pred,
  odds: p.odds,
  impl: p.impl,
  edge: p.edge,
}))));
"""


def _to_picks(games: list[dict]) -> list[dict]:
    """Run the shipped _gamesToPicks over `games` and return the rendered rows."""
    driver = REPO_ROOT / "tests" / "_dashboard_driver.js"
    driver.write_text(_DRIVER, encoding="utf-8")
    try:
        proc = subprocess.run(
            ["node", str(driver), str(DATA_JSX), json.dumps(games)],
            capture_output=True, text=True, check=False, cwd=str(REPO_ROOT),
        )
    finally:
        driver.unlink(missing_ok=True)

    assert proc.returncode == 0, f"node driver failed:\n{proc.stderr}"
    return json.loads(proc.stdout)


def _game(**overrides) -> dict:
    game = {
        "home_team": "Essendon",
        "away_team": "Carlton",
        "game_date": "2025-08-21",
        "venue": "M.C.G.",
        "home_win_prob": 0.30,
        "model_prediction": "Carlton",
        "confidence": "MED",
        "bet_recommended": False,
        "bet_amount": 0.0,
        "home_odds": HOME_ODDS,
        "away_odds": AWAY_ODDS,
        "tab_odds": HOME_ODDS,
    }
    game.update(overrides)
    return game


# ---------------------------------------------------------------------------
# Case A — home pick is priced with the home price
# ---------------------------------------------------------------------------

def test_home_pick_uses_home_price():
    (row,) = _to_picks([_game(home_win_prob=0.70, model_prediction="Essendon")])

    assert row["pick"] == "Essendon"
    assert row["pred"] == pytest.approx(0.70)
    assert row["odds"] == pytest.approx(HOME_ODDS)
    assert row["impl"] == pytest.approx(1 / HOME_ODDS)
    assert row["edge"] == pytest.approx((0.70 - 1 / HOME_ODDS) * 100)


# ---------------------------------------------------------------------------
# Case B — away pick is priced with the away price
# ---------------------------------------------------------------------------

def test_away_pick_uses_away_price():
    (row,) = _to_picks([_game(home_win_prob=0.30, model_prediction="Carlton")])

    assert row["pick"] == "Carlton"
    assert row["pred"] == pytest.approx(0.70)  # 1 - home_win_prob
    assert row["odds"] == pytest.approx(AWAY_ODDS), "away pick must not take the home price"
    assert row["impl"] == pytest.approx(1 / AWAY_ODDS)
    assert row["edge"] == pytest.approx((0.70 - 1 / AWAY_ODDS) * 100)


# ---------------------------------------------------------------------------
# Case C — the recommended bet is on the OTHER side from the displayed pick
# ---------------------------------------------------------------------------

def test_bet_odds_for_the_opposite_side_is_never_used():
    """The regression that shipped twice.

    Model favours Carlton (away); the value sits on Essendon (home), so
    bet_side/bet_odds describe the home side. The row is about Carlton and must
    be priced with Carlton's price, never with the recommended bet's price.
    """
    (row,) = _to_picks([
        _game(
            home_win_prob=0.4285,          # model favours Carlton (0.5715)
            model_prediction="Carlton",
            bet_recommended=True,
            bet_side="home",               # ...but the value is on Essendon
            bet_odds=3.846,                # the HOME price
            home_odds=3.846,
            away_odds=1.351,
        )
    ])

    assert row["pick"] == "Carlton"
    assert row["pred"] == pytest.approx(0.5715, abs=1e-4)
    assert row["odds"] == pytest.approx(1.351), "must use Carlton's price, not the bet's"
    assert row["odds"] != pytest.approx(3.846)

    truthful_edge = (0.5715 - 1 / 1.351) * 100
    assert row["edge"] == pytest.approx(truthful_edge, abs=1e-2)
    assert row["edge"] < 0, "pairing the pick with its own price yields a negative edge here"

    fabricated_edge = (0.5715 - 1 / 3.846) * 100  # ≈ +31.15, the old bug
    assert row["edge"] != pytest.approx(fabricated_edge, abs=1e-2)


# ---------------------------------------------------------------------------
# Case D — missing matching-side price must not borrow or fabricate
# ---------------------------------------------------------------------------

def test_away_pick_without_away_price_reports_unavailable():
    """A legacy payload carries only tab_odds (the home price).

    An away row has no price of its own, so odds/impl/edge must be null. The
    home price is the other side's number and borrowing it invents an edge.
    """
    game = _game(home_win_prob=0.30, model_prediction="Carlton")
    game.pop("away_odds")
    game.pop("home_odds")
    (row,) = _to_picks([game])

    assert row["pick"] == "Carlton"
    assert row["odds"] is None, "must not borrow the home price for an away pick"
    assert row["impl"] is None
    assert row["edge"] is None


def test_home_pick_falls_back_to_tab_odds():
    """tab_odds IS the home price, so a home pick may legitimately use it."""
    game = _game(home_win_prob=0.70, model_prediction="Essendon")
    game.pop("home_odds")
    game.pop("away_odds")
    (row,) = _to_picks([game])

    assert row["odds"] == pytest.approx(HOME_ODDS)
    assert row["edge"] == pytest.approx((0.70 - 1 / HOME_ODDS) * 100)


def test_zero_or_missing_price_is_not_treated_as_a_number():
    """A 0 or null price must not become an infinite implied probability."""
    for bad in (0, None):
        game = _game(home_win_prob=0.70, model_prediction="Essendon",
                     home_odds=bad, tab_odds=bad)
        (row,) = _to_picks([game])
        assert row["odds"] is None, f"price {bad!r} should read as unavailable"
        assert row["impl"] is None
        assert row["edge"] is None


# ---------------------------------------------------------------------------
# Payload contract — the producer must supply what the invariant needs
# ---------------------------------------------------------------------------

def test_demo_payload_carries_both_side_prices_consistently():
    """Every demo game must expose both prices, and bet_odds must match bet_side."""
    payload = json.loads((REPO_ROOT / "examples" / "sample_predictions.json").read_text())

    for game in payload["games"]:
        label = f"{game['home_team']} v {game['away_team']}"
        assert game.get("home_odds") is not None, f"{label}: missing home_odds"
        assert game.get("away_odds") is not None, f"{label}: missing away_odds"
        # tab_odds is defined as the home price.
        assert game["tab_odds"] == pytest.approx(game["home_odds"]), f"{label}: tab_odds != home"

        if game.get("bet_recommended"):
            expected = game["home_odds"] if game["bet_side"] == "home" else game["away_odds"]
            assert game["bet_odds"] == pytest.approx(expected), (
                f"{label}: bet_odds {game['bet_odds']} does not match "
                f"{game['bet_side']} price {expected}"
            )
