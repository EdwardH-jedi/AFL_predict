"""
tests/test_demo.py
-------------------
Guards `make demo` — the one command a reviewer is most likely to run first.

It must work from a fresh clone with no .env, no database, no API key, and no
network. These tests assert that contract, plus the shape of the payload the
static dashboard fetches, plus determinism (the demo is a portfolio artifact;
two runs of the same checkout must not disagree).
"""

from __future__ import annotations

import json
from contextlib import contextmanager

import pytest

from demo import run_demo


@contextmanager
def _redirected_outputs(out_dir):
    """Point every demo output path at a temp directory, then restore.

    All THREE module-level paths must be redirected. Missing one lets the test
    suite rewrite a tracked file under examples/, which dirties the working tree
    and fails CI's clean-tree gate — the exact bug this helper exists to prevent.
    """
    paths = {
        "predictions": out_dir / "predictions.json",
        "summary": out_dir / "summary.json",
        "example": out_dir / "example_predictions.json",
    }
    original = (
        run_demo.PREDICTIONS_JSON,
        run_demo.SUMMARY_JSON,
        run_demo.EXAMPLE_PREDICTIONS_JSON,
    )
    run_demo.PREDICTIONS_JSON = paths["predictions"]
    run_demo.SUMMARY_JSON = paths["summary"]
    run_demo.EXAMPLE_PREDICTIONS_JSON = paths["example"]
    try:
        yield paths
    finally:
        (
            run_demo.PREDICTIONS_JSON,
            run_demo.SUMMARY_JSON,
            run_demo.EXAMPLE_PREDICTIONS_JSON,
        ) = original


@pytest.fixture(scope="module")
def payload(tmp_path_factory) -> dict:
    """Run the demo once, redirecting every output into a temp directory."""
    out = tmp_path_factory.mktemp("demo")
    with _redirected_outputs(out) as paths:
        assert run_demo.main(["--json-only", "--write-example"]) == 0
        data = json.loads(paths["predictions"].read_text())
        data["_summary_artifact"] = json.loads(paths["summary"].read_text())
        data["_example_predictions"] = json.loads(paths["example"].read_text())
    return data


def test_sample_data_is_committed():
    """The demo must not depend on anything a clone would be missing."""
    assert run_demo.SAMPLE_CSV.exists(), f"{run_demo.SAMPLE_CSV} must be in the repository"


def test_demo_runs_without_network_credentials_or_database(payload):
    """A successful run under the test environment (no .env, no DB) is the assertion."""
    assert payload["games"], "demo produced no games"
    assert payload["demo"] is True


def test_payload_matches_the_dashboard_contract(payload):
    for key in ("generated_at", "season", "round", "games", "summary", "performance"):
        assert key in payload, f"predictions.json missing required key {key!r}"

    for key in ("total_bets_today", "total_amount", "paper_trade"):
        assert key in payload["summary"]

    for key in ("total_predictions", "correct", "accuracy", "total_pnl", "current_streak"):
        assert key in payload["performance"]

    for game in payload["games"]:
        for key in (
            "home_team",
            "away_team",
            "game_date",
            "venue",
            "model_prediction",
            "home_win_prob",
            "confidence",
            "bet_recommended",
            "bet_amount",
            "tab_odds",
        ):
            assert key in game, f"game missing required key {key!r}"


def test_probabilities_are_valid_and_complementary(payload):
    for game in payload["games"]:
        prob = game["home_win_prob"]
        assert 0.0 <= prob <= 1.0, f"probability out of range: {prob}"
        assert game["confidence"] in ("LOW", "MED", "HIGH")
        # The stated prediction must agree with the probability it came from.
        expected = game["home_team"] if prob >= 0.5 else game["away_team"]
        assert game["model_prediction"] == expected


def test_paper_trading_is_asserted_in_the_payload(payload):
    """The payload must say 'paper trade' so no consumer can infer otherwise."""
    assert payload["summary"]["paper_trade"] is True
    assert "paper trading only" in payload["demo_notice"].lower()
    assert payload["_summary_artifact"]["recommendations"]["paper_trade"] is True


def test_sample_data_is_clearly_labelled_as_sample(payload):
    """A reviewer must not mistake demo output for a live forecast."""
    notice = payload["demo_notice"].lower()
    assert "sample data" in notice
    assert "not a live forecast" in notice


def test_stakes_respect_the_kelly_cap(payload):
    """No recommendation may exceed the configured stake ceiling."""
    ceiling = run_demo.MAX_KELLY_FRACTION * run_demo.DEMO_BANKROLL
    for game in payload["games"]:
        assert game["bet_amount"] <= ceiling + 1e-9, (
            f"{game['home_team']} v {game['away_team']} staked "
            f"{game['bet_amount']} above the {ceiling} cap"
        )
        if not game["bet_recommended"]:
            assert game["bet_amount"] == 0.0


def test_summary_totals_agree_with_the_games_list(payload):
    bets = [g for g in payload["games"] if g["bet_recommended"]]
    assert payload["summary"]["total_bets_today"] == len(bets)
    assert payload["summary"]["total_amount"] == pytest.approx(
        round(sum(g["bet_amount"] for g in bets), 2)
    )


def test_ensemble_weights_come_from_settings(payload):
    """The demo must showcase the production blend, not a bespoke one."""
    from config.settings import Settings

    configured = set(Settings().ensemble_weights)
    reported = set(payload["ensemble_weights"])
    # Reported weights are the configured ones minus any component whose optional
    # dependency is missing in this environment; never anything extra.
    assert reported <= configured
    assert len(reported) >= 2
    assert sum(payload["ensemble_weights"].values()) == pytest.approx(1.0, abs=1e-3)


def test_holdout_split_is_strictly_temporal():
    """The demo's single fold must obey the same leakage rule as the backtester."""
    df = run_demo._load_sample()
    train, holdout = run_demo._split(df)
    assert train["match_time"].max() < holdout["match_time"].min()
    assert len(holdout) >= 5, "holdout round too small to be informative"


def test_demo_is_deterministic(payload, tmp_path):
    """Same checkout, same numbers — a portfolio artifact cannot drift per run."""
    with _redirected_outputs(tmp_path) as paths:
        run_demo.main(["--json-only", "--write-example"])
        second = json.loads(paths["predictions"].read_text())

    # generated_at is a wall-clock timestamp and is expected to differ.
    injected = ("generated_at", "_summary_artifact", "_example_predictions")
    first = {k: v for k, v in payload.items() if k not in injected}
    second = {k: v for k, v in second.items() if k != "generated_at"}
    assert first == second
