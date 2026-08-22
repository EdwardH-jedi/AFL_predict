"""
tests/test_ensemble_fold_isolation.py
--------------------------------------
Regression coverage for TrainableEnsemble fold isolation.

BacktestRunner reuses one ensemble instance across every fold. The original
implementation assigned surviving components back to `self.components` after a
fit failure, so a component that failed in fold 1 was silently absent from folds
2..N — one transient failure quietly changed the model being evaluated for the
rest of the run, and nothing reported it.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from models.base_model import BaseModel
from models.ensemble import TrainableEnsemble


class _Stub(BaseModel):
    """Component that can be made to fail `fit` on a chosen call index."""

    def __init__(self, name: str, prob: float, fail_on_calls: set[int] | None = None):
        self.name = name
        self.version = "test"
        self._prob = prob
        self._fail_on = fail_on_calls or set()
        self.fit_calls = 0

    def fit(self, X, y):
        self.fit_calls += 1
        if self.fit_calls in self._fail_on:
            raise RuntimeError(f"{self.name} unavailable on call {self.fit_calls}")

    def predict_proba(self, X: pd.DataFrame) -> pd.DataFrame:
        out = X[["match_id"]].copy().reset_index(drop=True)
        out["home_win_prob"] = np.full(len(X), self._prob)
        out["away_win_prob"] = 1.0 - out["home_win_prob"]
        return out

    def save(self, artifacts_dir):  # pragma: no cover
        raise NotImplementedError


@pytest.fixture()
def X() -> pd.DataFrame:
    return pd.DataFrame({"match_id": [1, 2, 3]})


@pytest.fixture()
def y() -> pd.Series:
    return pd.Series([1, 0, 1])


def test_component_failure_does_not_leak_into_the_next_fold(X, y):
    """The canonical roster must be restored before every fit."""
    flaky = _Stub("flaky", 0.8, fail_on_calls={1})  # fails fold 1 only
    stable = _Stub("stable", 0.4)
    ensemble = TrainableEnsemble([(flaky, 0.5), (stable, 0.5)])

    # Fold 1 — flaky fails, blend degrades to `stable` alone.
    ensemble.fit(X, y)
    assert set(ensemble.weights) == {"stable"}
    assert ensemble.predict_proba(X)["home_win_prob"].iloc[0] == pytest.approx(0.4)

    # Fold 2 — flaky recovers. It MUST be back in the blend.
    ensemble.fit(X, y)
    assert set(ensemble.weights) == {"flaky", "stable"}, (
        "a fold-1 failure permanently removed the component from later folds"
    )
    assert ensemble.predict_proba(X)["home_win_prob"].iloc[0] == pytest.approx(0.6)


def test_canonical_roster_is_never_mutated(X, y):
    flaky = _Stub("flaky", 0.8, fail_on_calls={1, 2, 3})
    stable = _Stub("stable", 0.4)
    ensemble = TrainableEnsemble([(flaky, 0.5), (stable, 0.5)])

    for _ in range(3):
        ensemble.fit(X, y)

    assert ensemble.canonical_weights == {"flaky": 0.5, "stable": 0.5}
    assert len(ensemble._canonical) == 2


def test_surviving_weights_are_renormalised_per_fold(X, y):
    a = _Stub("a", 1.0)
    b = _Stub("b", 0.0, fail_on_calls={1})
    ensemble = TrainableEnsemble([(a, 0.25), (b, 0.75)])

    ensemble.fit(X, y)                       # b fails -> a carries the whole blend
    assert ensemble.weights == pytest.approx({"a": 1.0})

    ensemble.fit(X, y)                       # both available -> canonical split
    assert ensemble.weights == pytest.approx({"a": 0.25, "b": 0.75})


def test_every_fold_composition_is_recorded(X, y):
    """§14 requires the active component set to be auditable per window."""
    flaky = _Stub("flaky", 0.8, fail_on_calls={2})
    stable = _Stub("stable", 0.4)
    ensemble = TrainableEnsemble([(flaky, 0.5), (stable, 0.5)])

    ensemble.fit(X, y)   # both
    ensemble.fit(X, y)   # flaky fails
    ensemble.fit(X, y)   # both again

    comps = ensemble.fold_compositions
    assert [c["n_components"] for c in comps] == [2, 1, 2]
    assert set(comps[1]["weights"]) == {"stable"}
    assert set(comps[2]["weights"]) == {"flaky", "stable"}


def test_all_components_failing_still_raises(X, y):
    ensemble = TrainableEnsemble(
        [(_Stub("a", 0.5, fail_on_calls={1}), 0.5), (_Stub("b", 0.5, fail_on_calls={1}), 0.5)]
    )
    with pytest.raises(RuntimeError, match="every component failed to fit"):
        ensemble.fit(X, y)
