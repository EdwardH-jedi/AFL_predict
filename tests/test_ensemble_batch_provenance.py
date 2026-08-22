"""
tests/test_ensemble_batch_provenance.py
----------------------------------------
Guards coherent ensemble assembly in production (§6).

The defect: each component was selected independently as its own best-Brier run
across all history. A production ensemble could therefore pair a logistic
regression trained in March with an XGBoost trained in July — different training
data, different feature schema, different code — and nothing recorded that the
combination had never existed as a trained whole. The weights belonged to a
configuration; the components belonged to nothing.

Components must now come from a single `training_batch_id`.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

import pytest

from db.models.model_runs import ModelRun


class _Dummy:
    def __init__(self, name: str):
        self.name = name


def _run(model_name: str, *, batch: str | None, brier: float = 0.20,
         n_features: int | None = None, age_days: int = 0) -> ModelRun:
    meta = json.dumps({"n_features": n_features}) if n_features is not None else None
    return ModelRun(
        model_name=model_name,
        model_version="0.1",
        status="completed",
        brier_score=brier,
        training_batch_id=batch,
        metadata_json=meta,
        completed_at=datetime.now(tz=UTC) - timedelta(days=age_days),
    )


@pytest.fixture()
def recs(monkeypatch):
    from orchestration.jobs import generate_recommendations as module
    monkeypatch.setattr(module, "_instantiate_model", lambda run: _Dummy(run.model_name))
    return module


def _full_batch(recs, batch: str, **kw) -> list[ModelRun]:
    """One run per configured component, all sharing a batch id.

    Components whose schema is checked (logistic, XGBoost) get the current
    expected feature count so the batch is genuinely compatible.
    """
    expected = recs._expected_n_features_by_model()
    return [
        _run(name, batch=batch, n_features=expected.get(name), **kw)
        for name in recs.settings.ensemble_weights
    ]


def test_components_from_one_batch_are_accepted(db_session, recs):
    db_session.add_all(_full_batch(recs, "batch-1"))
    db_session.commit()

    batch_id, runs = recs._select_coherent_batch(
        db_session, set(recs.settings.ensemble_weights)
    )
    assert batch_id == "batch-1"
    assert set(runs) == set(recs.settings.ensemble_weights)


def test_components_are_never_mixed_across_batches(db_session, recs):
    """The regression: two half-batches must not combine into one ensemble."""
    names = list(recs.settings.ensemble_weights)
    half = len(names) // 2
    # batch-old holds some components with excellent scores, batch-new the rest.
    db_session.add_all(
        [_run(n, batch="batch-old", brier=0.05, age_days=90) for n in names[:half]]
        + [_run(n, batch="batch-new", brier=0.30, age_days=1) for n in names[half:]]
    )
    db_session.commit()

    batch_id, runs = recs._select_coherent_batch(db_session, set(names))
    assert batch_id is None, "components were combined across training batches"
    assert runs == {}


def test_batch_missing_a_component_is_rejected(db_session, recs):
    names = list(recs.settings.ensemble_weights)
    db_session.add_all([_run(n, batch="batch-1") for n in names[:-1]])
    db_session.commit()

    batch_id, _ = recs._select_coherent_batch(db_session, set(names))
    assert batch_id is None


def test_batch_with_stale_feature_schema_is_rejected(db_session, recs):
    """A model trained against a different feature count is not compatible."""
    expected = recs._expected_n_features_by_model()
    names = list(recs.settings.ensemble_weights)
    runs = []
    for n in names:
        stale = expected.get(n)
        runs.append(_run(n, batch="batch-1",
                         n_features=(stale - 1) if stale is not None else None))
    db_session.add_all(runs)
    db_session.commit()

    batch_id, _ = recs._select_coherent_batch(db_session, set(names))
    assert batch_id is None, "a batch with a stale feature schema was accepted"


def test_runs_without_a_batch_id_are_not_eligible(db_session, recs):
    """Pre-migration runs have unrecorded provenance and cannot be trusted."""
    db_session.add_all([_run(n, batch=None) for n in recs.settings.ensemble_weights])
    db_session.commit()

    batch_id, _ = recs._select_coherent_batch(
        db_session, set(recs.settings.ensemble_weights)
    )
    assert batch_id is None


def test_most_recent_qualifying_batch_wins(db_session, recs):
    """Recency, not score.

    Choosing the best-scoring batch across history would be selection on the
    same metric the models are judged by — the ensemble equivalent of the
    hyperparameter leakage this project already corrected once.
    """
    db_session.add_all(
        _full_batch(recs, "older", brier=0.05, age_days=60)
        + _full_batch(recs, "newer", brier=0.40, age_days=1)
    )
    db_session.commit()

    batch_id, _ = recs._select_coherent_batch(
        db_session, set(recs.settings.ensemble_weights)
    )
    assert batch_id == "newer"


def test_ensemble_falls_back_to_single_model_when_no_batch_qualifies(db_session, recs):
    db_session.add_all([_run(n, batch=None) for n in recs.settings.ensemble_weights])
    db_session.commit()

    ensemble, ref = recs._try_build_ensemble(db_session)
    assert ensemble is None and ref is None
