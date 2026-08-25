"""
tests/test_dashboard_contract.py
---------------------------------
Contract smoke tests for the read-only legacy dashboard API.

These tests intentionally assert stable top-level and item-level fields only.
They do not require live AFL data, do not trigger pipeline jobs, and do not
exercise any betting execution path.
"""


import pytest

from db.base import Base


@pytest.fixture(autouse=True)
def _ensure_dashboard_tables(db_session):
    """Create dashboard ORM tables after all model modules are registered."""
    import db.models  # noqa: F401

    Base.metadata.create_all(bind=db_session.connection())


def test_dashboard_summary_contract(db_session):
    from api.routes.dashboard import get_summary

    body = get_summary(db_session)
    assert set(body) == {"source", "data"}
    assert body["source"] in {"artifact", "live"}

    data = body["data"]
    assert "pipeline" in data
    assert "bankroll" in data
    assert "recommendations" in data
    assert "date" in data or "generated_at" in data


def test_dashboard_performance_contract(db_session):
    from api.routes.dashboard import get_performance

    body = get_performance(db_session)
    assert set(body) == {"summary", "bets", "cumulative_pl", "model_runs"}

    assert set(body["summary"]) == {
        "total_bets",
        "settled",
        "pending",
        "void",
        "wins",
        "losses",
        "win_rate_pct",
        "total_pl_units",
        "roi_pct",
    }
    assert isinstance(body["bets"], list)
    assert isinstance(body["cumulative_pl"], list)
    assert isinstance(body["model_runs"], list)


def test_dashboard_bankroll_contract(db_session):
    from api.routes.dashboard import get_bankroll_trend

    body = get_bankroll_trend(db=db_session)
    assert {"days", "current", "drawdown", "series"}.issubset(body)
    assert isinstance(body["series"], list)


def test_dashboard_recommendations_contract(db_session):
    from api.routes.dashboard import get_recommendations

    body = get_recommendations(db=db_session)
    assert set(body) == {"limit", "count", "recommendations"}
    assert isinstance(body["recommendations"], list)


def test_dashboard_freshness_contract(db_session):
    from api.routes.dashboard import get_freshness

    body = get_freshness(db_session)
    assert set(body) == {
        "checked_at",
        "odds_age_hours",
        "odds_stale",
        "afl_age_hours",
        "afl_stale",
        "warnings",
    }
    assert isinstance(body["warnings"], list)


def test_dashboard_readiness_contract(monkeypatch):
    from api.routes import dashboard

    class _Report:
        def to_dict(self):
            return {
                "generated_at": "2026-01-01T00:00:00+00:00",
                "overall": "not_ready",
                "checks": [],
            }

    monkeypatch.setattr(dashboard, "evaluate_readiness", lambda: _Report())

    body = dashboard.get_readiness()
    assert {"generated_at", "overall", "checks"}.issubset(body)
    assert isinstance(body["checks"], list)


def test_dashboard_calibration_contract(db_session):
    from api.routes.dashboard import get_calibration

    body = get_calibration(db=db_session)
    assert "available" in body
    if body["available"]:
        assert {"model_run", "n_settled", "ece", "reliability_bins", "per_phase"}.issubset(body)
    else:
        assert "reason" in body


def test_dashboard_clv_contract(db_session):
    from api.routes.dashboard import get_clv_summary

    body = get_clv_summary(db_session)
    assert set(body) == {"clv"}
    assert set(body["clv"]) == {
        "n_bets",
        "n_with_clv",
        "beat_closing_line",
        "avg_clv",
        "avg_clv_pct",
        "median_clv_pct",
    }


def test_backtest_summary_ensemble_weights_contract(db_session):
    """ensemble_weights must report the members/values actually used by the
    production ensemble (single-sourced from config.settings)."""
    from api.routes.dashboard_ui import backtest_summary
    from config.settings import get_settings

    settings = get_settings()
    body = backtest_summary(db_session)

    weights = body.ensemble_weights
    assert set(weights.model_fields) == {"logistic", "elo", "xgboost", "poisson"}
    assert weights.logistic == settings.ensemble_weight_logistic
    assert weights.elo == settings.ensemble_weight_elo
    assert weights.xgboost == settings.ensemble_weight_xgboost
    assert weights.poisson == settings.ensemble_weight_poisson
