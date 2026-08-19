from __future__ import annotations

import json
from datetime import UTC, datetime

from db.models.model_runs import ModelRun


class _DummyModel:
    def __init__(self, name: str):
        self.name = name


def _completed_run(model_name: str, **kwargs) -> ModelRun:
    defaults = {
        "model_version": "0.1",
        "status": "completed",
        "completed_at": datetime.now(tz=UTC),
        "brier_score": 0.2,
    }
    defaults.update(kwargs)
    return ModelRun(model_name=model_name, **defaults)


def test_schema_compatibility_checks_current_feature_count():
    from orchestration.jobs.generate_recommendations import (
        _expected_n_features_by_model,
        _is_model_run_schema_compatible,
    )

    expected = _expected_n_features_by_model()["xgboost"]
    compatible = _completed_run(
        "xgboost",
        metadata_json=json.dumps({"n_features": expected}),
    )
    stale = _completed_run(
        "xgboost",
        metadata_json=json.dumps({"n_features": expected - 1}),
    )

    assert _is_model_run_schema_compatible(compatible) is True
    assert _is_model_run_schema_compatible(stale) is False


def test_load_best_model_fallback_skips_stale_best_brier_run(db_session, monkeypatch):
    from orchestration.jobs import generate_recommendations as recs

    db_session.query(ModelRun).delete()
    db_session.commit()

    expected = recs._expected_n_features_by_model()["xgboost"]
    stale_xgb = _completed_run(
        "xgboost",
        brier_score=0.10,
        metadata_json=json.dumps({"n_features": expected - 2}),
    )
    elo = _completed_run(
        "elo_baseline",
        brier_score=0.20,
        metadata_json=None,
    )
    db_session.add_all([stale_xgb, elo])
    db_session.commit()

    monkeypatch.setattr(recs, "_try_build_ensemble", lambda db: (None, None))
    monkeypatch.setattr(recs, "_instantiate_model", lambda run: _DummyModel(run.model_name))

    model, run = recs._load_best_model(db_session)

    assert run.id == elo.id
    assert model.name == "elo_baseline"


def test_try_build_ensemble_uses_first_loaded_component_run_when_no_xgb_or_logistic(
    db_session, monkeypatch
):
    from orchestration.jobs import generate_recommendations as recs

    db_session.query(ModelRun).delete()
    db_session.commit()

    elo = _completed_run("elo_baseline", brier_score=0.21)
    poisson = _completed_run("poisson", brier_score=0.22)
    db_session.add_all([elo, poisson])
    db_session.commit()

    monkeypatch.setattr(recs, "_instantiate_model", lambda run: _DummyModel(run.model_name))
    monkeypatch.setattr(recs, "Ensemble", lambda components: {"components": components})

    ensemble, ref_run = recs._try_build_ensemble(db_session)

    assert ensemble is not None
    assert ref_run.id == poisson.id
