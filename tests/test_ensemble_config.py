"""
tests/test_ensemble_config.py
------------------------------
Guards the single source of truth for production ensemble weights.

The failure this file exists to prevent: a second, hard-coded weight table
living next to the production code path. When that happened, the recommendation
job blended logistic/xgboost/poisson/elo while the dashboard API reported
bookmaker/elo/xgboost/poisson — two different ensembles, no failing test.

Two invariants are asserted here:
  1. The weight keys are the *persisted* model names (BaseModel.name), because
     that is what generate_recommendations matches ModelRun.model_name against.
     A typo'd key finds zero runs and silently degrades to a single model.
  2. Every production consumer reads Settings.ensemble_weights, not its own dict.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from config.settings import Settings
from models.base_model import BaseModel
from models.bookmaker_baseline import BookmakerBaseline
from models.elo_baseline import EloBaseline
from models.ensemble import Ensemble
from models.logistic_baseline import LogisticBaseline
from models.poisson_model import PoissonModel
from models.xgboost_model import XGBoostModel


class _StubModel(BaseModel):
    """Component returning a fixed home-win probability for every row."""

    def __init__(self, name: str, prob: float, fail: bool = False):
        self.name = name
        self.version = "test"
        self._prob = prob
        self._fail = fail

    def fit(self, X, y):  # pragma: no cover - not exercised
        pass

    def predict_proba(self, X: pd.DataFrame) -> pd.DataFrame:
        if self._fail:
            raise RuntimeError(f"{self.name} is unavailable")
        out = X[["match_id"]].copy().reset_index(drop=True)
        out["home_win_prob"] = np.full(len(X), self._prob)
        out["away_win_prob"] = 1.0 - out["home_win_prob"]
        return out

    def save(self, artifacts_dir):  # pragma: no cover - not exercised
        raise NotImplementedError


@pytest.fixture()
def X() -> pd.DataFrame:
    return pd.DataFrame({"match_id": [1, 2, 3]})


# ---------------------------------------------------------------------------
# 1. Weight keys must match the persisted model names
# ---------------------------------------------------------------------------

def test_weight_keys_match_persisted_model_names():
    """Every configured weight key must be a real BaseModel.name.

    Weights are looked up against ModelRun.model_name, which is written from
    BaseModel.name. A key that matches no model class is dead configuration
    that fails silently rather than loudly.
    """
    known_names = {
        cls.name
        for cls in (
            LogisticBaseline,
            XGBoostModel,
            PoissonModel,
            EloBaseline,
            BookmakerBaseline,
        )
    }
    settings = Settings()
    unknown = set(settings.ensemble_weights) - known_names
    assert not unknown, f"ensemble_weights has keys matching no model class: {unknown}"


def test_default_production_blend_is_the_four_forecasting_models():
    """Defaults must describe the blend production actually runs."""
    weights = Settings().ensemble_weights
    assert set(weights) == {"logistic_baseline", "xgboost", "poisson", "elo_baseline"}
    # Bookmaker baseline is the benchmark, not a component — excluded at 0.0.
    assert "bookmaker_baseline" not in weights


def test_zero_weighted_component_is_excluded_not_loaded():
    """A component zeroed out in config must disappear from the blend."""
    settings = Settings(ensemble_weight_poisson=0.0)
    assert "poisson" not in settings.ensemble_weights

    settings = Settings(ensemble_weight_bookmaker_baseline=0.25)
    assert settings.ensemble_weights["bookmaker_baseline"] == pytest.approx(0.25)


def test_env_vars_override_weights(monkeypatch):
    """Weights are operator-tunable through the environment, like every other setting."""
    monkeypatch.setenv("ENSEMBLE_WEIGHT_XGBOOST", "0.60")
    monkeypatch.setenv("ENSEMBLE_WEIGHT_POISSON", "0")
    settings = Settings(_env_file=None)
    assert settings.ensemble_weights["xgboost"] == pytest.approx(0.60)
    assert "poisson" not in settings.ensemble_weights


# ---------------------------------------------------------------------------
# 2. Production consumers read the centralised config
# ---------------------------------------------------------------------------

def test_recommendation_job_has_no_private_weight_table():
    """generate_recommendations must not reintroduce its own weight dict."""
    from orchestration.jobs import generate_recommendations as recs

    assert not hasattr(recs, "_ENSEMBLE_WEIGHTS"), (
        "generate_recommendations reintroduced a module-level weight table; "
        "it must read config.settings.Settings.ensemble_weights instead."
    )


def test_recommendation_job_builds_ensemble_from_settings_weights(db_session, monkeypatch):
    """The ensemble builder must consume exactly the configured components."""
    from orchestration.jobs import generate_recommendations as recs

    configured = {"logistic_baseline": 0.4, "xgboost": 0.6}
    monkeypatch.setattr(
        type(recs.settings),
        "ensemble_weights",
        property(lambda self: configured),
    )

    requested: list[str] = []

    def fake_query(model):
        return _FilterCapture(requested)

    class _FilterCapture:
        """Records which model_name each component query asks for."""

        def __init__(self, sink):
            self._sink = sink

        def filter(self, *criteria, **k):
            for c in criteria:
                text = str(c)
                if "model_name" in text:
                    self._sink.append(text)
            return self

        def order_by(self, *a, **k):
            return self

        def limit(self, *a, **k):
            return self

        def all(self):
            return []

    monkeypatch.setattr(db_session, "query", fake_query)
    model, ref = recs._try_build_ensemble(db_session)

    # No runs exist, so no ensemble is built — but exactly the configured
    # components must have been looked up, and nothing else.
    assert model is None and ref is None
    assert len(requested) == len(configured)


def test_no_positive_weights_falls_back_instead_of_crashing(db_session, monkeypatch):
    """An all-zero weight config must degrade to single-model, not raise."""
    from orchestration.jobs import generate_recommendations as recs

    monkeypatch.setattr(
        type(recs.settings), "ensemble_weights", property(lambda self: {})
    )
    assert recs._try_build_ensemble(db_session) == (None, None)


def test_dashboard_reports_the_same_weights_as_production():
    """The dashboard must not display a blend production never used."""
    from api.routes.dashboard_ui import EnsembleWeights

    reported = EnsembleWeights.from_settings()
    production = Settings().ensemble_weights

    assert reported.logistic == pytest.approx(production.get("logistic_baseline", 0.0))
    assert reported.xgboost == pytest.approx(production.get("xgboost", 0.0))
    assert reported.poisson == pytest.approx(production.get("poisson", 0.0))
    assert reported.elo == pytest.approx(production.get("elo_baseline", 0.0))
    assert reported.bookmaker == pytest.approx(production.get("bookmaker_baseline", 0.0))


# ---------------------------------------------------------------------------
# 3. Ensemble normalisation / degradation behaviour
# ---------------------------------------------------------------------------

def test_weights_are_normalised_regardless_of_scale(X):
    """Relative weights are what matter; absolute scale must not shift output."""
    unit = Ensemble([(_StubModel("a", 0.8), 0.30), (_StubModel("b", 0.4), 0.10)])
    scaled = Ensemble([(_StubModel("a", 0.8), 3.0), (_StubModel("b", 0.4), 1.0)])

    assert unit.predict_proba(X)["home_win_prob"].tolist() == pytest.approx(
        scaled.predict_proba(X)["home_win_prob"].tolist()
    )
    # 0.75 * 0.8 + 0.25 * 0.4
    assert unit.predict_proba(X)["home_win_prob"].iloc[0] == pytest.approx(0.7)


def test_missing_component_renormalises_over_survivors(X):
    """A component that fails at predict time must not silently shrink probabilities."""
    ensemble = Ensemble(
        [
            (_StubModel("good_a", 0.8), 0.30),
            (_StubModel("good_b", 0.6), 0.10),
            (_StubModel("broken", 0.0, fail=True), 0.60),
        ]
    )
    preds = ensemble.predict_proba(X)

    # Survivors carry 0.30/0.10 → renormalised to 0.75/0.25.
    assert preds["home_win_prob"].iloc[0] == pytest.approx(0.75 * 0.8 + 0.25 * 0.6)
    # Probabilities must still be a valid distribution, not a weight-deflated one.
    assert (preds["home_win_prob"] + preds["away_win_prob"]).tolist() == pytest.approx(
        [1.0, 1.0, 1.0]
    )


def test_all_components_failing_raises_rather_than_returning_garbage(X):
    ensemble = Ensemble(
        [
            (_StubModel("broken_a", 0.0, fail=True), 0.5),
            (_StubModel("broken_b", 0.0, fail=True), 0.5),
        ]
    )
    with pytest.raises(RuntimeError, match="all component models failed"):
        ensemble.predict_proba(X)


def test_all_zero_weights_rejected_at_construction():
    with pytest.raises(ValueError, match="all component weights are zero"):
        Ensemble([(_StubModel("a", 0.5), 0.0), (_StubModel("b", 0.5), 0.0)])
