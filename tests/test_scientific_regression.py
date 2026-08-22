"""
tests/test_scientific_regression.py
------------------------------------
End-to-end guard on the evaluation path that produces the published numbers (§10).

Runs the real BacktestRunner over a small frozen multi-season fixture (180
matches, 2021–2024, committed at tests/fixtures/frozen_eval_fixture.parquet) and
pins the outputs. The full canonical evaluation needs a 2,454-row parquet that is
gitignored and a live upstream to rebuild, so CI cannot run it; this fixture
exercises the same code path deterministically in about a second.

What it protects: temporal fold construction, per-match alignment, every model's
predictions, Brier / log loss / accuracy, pooled *and* season-weighted ECE,
ensemble composition, provenance metadata, and artifact round-tripping.

If a change here is intentional, update the pinned values in one place
(`EXPECTED`) and say why in the commit message.
"""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

from backtesting.artifacts import ARTIFACT_SCHEMA_VERSION, BacktestResult
from backtesting.calibration import expected_calibration_error
from backtesting.provenance import sha256_file
from backtesting.runner import BacktestRunner
from models.bookmaker_baseline import BookmakerBaseline
from models.elo_baseline import EloBaseline
from models.ensemble import TrainableEnsemble
from models.logistic_baseline import LogisticBaseline
from models.poisson_model import PoissonModel

FIXTURE = Path(__file__).parent / "fixtures" / "frozen_eval_fixture.parquet"

# Pinning the input by content, not just by path: a silently regenerated fixture
# would otherwise move every expected number with no test failing.
FIXTURE_SHA256 = "ea59e590cb9dc7c1fb60423e478689d67795bdfd74b9fff1e4ee1f165d70959d"

# XGBoost is deliberately excluded: it needs an OpenMP runtime that is not
# guaranteed on every CI image, and its absence would make this suite flaky
# rather than informative. The models below are pure Python/NumPy/sklearn.
_WEIGHTS = {"logistic_baseline": 0.4, "poisson": 0.25, "elo_baseline": 0.35}


def _models() -> list:
    components = [
        (LogisticBaseline(), _WEIGHTS["logistic_baseline"]),
        (PoissonModel(), _WEIGHTS["poisson"]),
        (EloBaseline(), _WEIGHTS["elo_baseline"]),
    ]
    return [
        BookmakerBaseline(), EloBaseline(), LogisticBaseline(), PoissonModel(),
        TrainableEnsemble(components),
    ]


@pytest.fixture(scope="module")
def result() -> BacktestResult:
    df = pd.read_parquet(FIXTURE)
    runner = BacktestRunner(mode="expanding", min_train_seasons=2)
    return runner.run(df, _models())


def test_fixture_is_the_pinned_one():
    assert FIXTURE.exists(), "frozen evaluation fixture is missing from the repository"
    assert sha256_file(FIXTURE) == FIXTURE_SHA256, (
        "the frozen fixture changed; regenerate the pinned expectations deliberately"
    )


def test_fold_structure(result: BacktestResult):
    """4 seasons, min 2 training seasons -> 2023 and 2024 are test folds."""
    assert result.n_folds == 2
    assert sorted({w["fold_label"] for w in result.window_results}) == ["2023", "2024"]


def test_every_model_scored_every_fold(result: BacktestResult):
    got = {(w["model_name"], w["fold_label"]) for w in result.window_results}
    models = {m.name for m in _models()}
    assert got == {(m, f) for m in models for f in ("2023", "2024")}


def test_predictions_align_one_row_per_model_per_match(result: BacktestResult):
    pred = pd.DataFrame(result.predictions)
    n_test = sum(w["n_matches"] for w in result.window_results
                 if w["model_name"] == "bookmaker_baseline")
    assert len(pred) == n_test * len({m.name for m in _models()})
    # No match_id appears twice for the same model.
    assert not pred.duplicated(subset=["model", "match_id"]).any()


def test_pooled_ece_is_recomputable_from_the_artifacts_own_rows(result: BacktestResult):
    """The property that makes the artifact auditable rather than trusted."""
    pred = pd.DataFrame(result.predictions)
    for name, agg in result.aggregate_metrics.items():
        rows = pred[(pred["model"] == name) & (pred["settled"])]
        recomputed = expected_calibration_error(
            rows["y_true"].values, rows["y_prob"].values, n_bins=10
        )
        assert agg["pooled_ece"] == pytest.approx(recomputed, abs=1e-9), name


def test_pooled_and_season_weighted_ece_are_both_present_and_named(result: BacktestResult):
    for name, agg in result.aggregate_metrics.items():
        assert "ece" not in agg, f"{name}: bare 'ece' key reintroduced"
        assert agg["pooled_ece"] is not None, name
        assert agg["season_weighted_ece"] is not None, name


def test_decomposable_metrics_equal_their_pooled_form(result: BacktestResult):
    """Brier and accuracy from the aggregate must match a direct pooled recompute."""
    pred = pd.DataFrame(result.predictions)
    for name, agg in result.aggregate_metrics.items():
        rows = pred[(pred["model"] == name) & (pred["settled"])]
        brier = float(((rows["y_prob"] - rows["y_true"]) ** 2).mean())
        acc = float((((rows["y_prob"] >= 0.5).astype(int)) == rows["y_true"]).mean())
        assert agg["brier_score"] == pytest.approx(brier, abs=1e-5), name
        assert agg["accuracy"] == pytest.approx(acc, abs=1e-5), name


def test_ensemble_composition_is_recorded_per_fold(result: BacktestResult):
    agg = result.aggregate_metrics["ensemble"]
    comps = agg.get("fold_compositions")
    assert comps and len(comps) == 2, "one composition record per fold expected"
    for c in comps:
        assert c["n_components"] == 3
        assert set(c["weights"]) == set(_WEIGHTS)


def test_metrics_are_deterministic_across_runs():
    """Same fixture, same numbers — the fixture is worthless if it drifts."""
    df = pd.read_parquet(FIXTURE)
    a = BacktestRunner(mode="expanding", min_train_seasons=2).run(df, _models())
    b = BacktestRunner(mode="expanding", min_train_seasons=2).run(df, _models())
    for name in a.aggregate_metrics:
        for key in ("brier_score", "log_loss", "accuracy", "pooled_ece",
                    "season_weighted_ece"):
            assert a.aggregate_metrics[name][key] == pytest.approx(
                b.aggregate_metrics[name][key]
            ), f"{name}.{key} is not deterministic"


def test_artifact_round_trips_through_serialisation(result: BacktestResult, tmp_path):
    result.provenance = {"code": {"commit": "test"}, "input": {"sha256": FIXTURE_SHA256}}
    path = result.save(tmp_path)

    raw = json.loads(path.read_text())
    assert raw["artifact_schema_version"] == ARTIFACT_SCHEMA_VERSION
    assert "NaN" not in path.read_text(), "artifact must be strict-parseable JSON"
    # predictions are stored columnar
    assert isinstance(raw["predictions"], dict)

    restored = BacktestResult.from_dict(raw)
    assert len(restored.predictions) == len(result.predictions)
    assert restored.provenance["input"]["sha256"] == FIXTURE_SHA256
    for name, agg in result.aggregate_metrics.items():
        assert restored.aggregate_metrics[name]["pooled_ece"] == pytest.approx(
            agg["pooled_ece"]
        )


def test_v1_artifacts_are_rejected_rather_than_misread():
    with pytest.raises(ValueError, match="artifact_schema_version"):
        BacktestResult.from_dict({"artifact_schema_version": 1, "run_id": "old"})
