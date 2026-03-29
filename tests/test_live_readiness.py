"""
tests/test_live_readiness.py
------------------------------
Unit tests for the live-readiness evaluator.

Each check is tested in isolation using in-memory DB rows.
No network calls or real ingestion.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest

from db.models.bankroll_logs import BankrollLog
from db.models.bet_outcomes import BetOutcome
from db.models.daily_pipeline_runs import DailyPipelineRun
from db.models.pipeline_runs import PipelineRun
from db.models.recommendations import Recommendation
from db.models.predictions import Prediction
from db.models.matches import Match


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def recs_and_outcomes(db_session):
    """Create a set of recommendations and BetOutcome rows in the test DB."""
    # Minimal Match
    match = Match(
        external_id="test-m1",
        home_team_id=1,
        away_team_id=2,
        match_time=datetime(2025, 4, 1, tzinfo=timezone.utc),
        round_number=1,
        season=2025,
    )
    db_session.add(match)
    db_session.flush()

    outcomes = []
    for i in range(80):
        pred = Prediction(
            match_id=match.id,
            model_run_id=1,
            home_win_prob=0.55,
            away_win_prob=0.45,
        )
        db_session.add(pred)
        db_session.flush()

        rec = Recommendation(
            prediction_id=pred.id,
            side="home",
            recommended_odds=1.90,
            stake_fraction=0.02,
            paper_trade=True,
            status="settled",
        )
        db_session.add(rec)
        db_session.flush()

        outcome = BetOutcome(
            recommendation_id=rec.id,
            won=(i % 2 == 0),  # alternating win/loss
            profit_loss_units=0.90 if i % 2 == 0 else -1.0,
            settled_at=datetime.now(tz=timezone.utc),
        )
        db_session.add(outcome)
        outcomes.append(outcome)

    db_session.flush()
    return outcomes


# ---------------------------------------------------------------------------
# Test: sample_size check
# ---------------------------------------------------------------------------

class TestSampleSizeCheck:
    def _run_check(self, db):
        from evaluation.live_readiness import _check_sample_size
        return _check_sample_size(db)

    def test_fail_when_no_outcomes(self, db_session):
        result = self._run_check(db_session)
        assert result.status == "fail"
        assert result.value == 0

    def test_pass_when_above_threshold(self, db_session, recs_and_outcomes):
        with patch("evaluation.live_readiness.settings") as s:
            s.readiness_min_settled_bets = 50
            s.readiness_max_drawdown = 0.25
            s.readiness_max_ece = 0.06
            s.readiness_max_failed_jobs_7d = 2
            result = self._run_check(db_session)
        assert result.status == "pass"
        assert result.value == 80

    def test_warn_between_50_and_100(self, db_session, recs_and_outcomes):
        with patch("evaluation.live_readiness.settings") as s:
            s.readiness_min_settled_bets = 100
            result = self._run_check(db_session)
        # 80 bets, threshold 100, warn zone is >=50
        assert result.status == "warn"


# ---------------------------------------------------------------------------
# Test: drawdown check
# ---------------------------------------------------------------------------

class TestDrawdownCheck:
    def _run_check(self, db):
        from evaluation.live_readiness import _check_drawdown
        return _check_drawdown(db)

    def test_warn_when_no_bankroll(self, db_session):
        result = self._run_check(db_session)
        assert result.status == "warn"

    def test_pass_on_low_drawdown(self, db_session):
        for bal in [1000.0, 1010.0, 990.0, 1005.0]:
            db_session.add(BankrollLog(
                event_type="bet_settled",
                balance_after=bal,
                amount=0.0,
            ))
        db_session.flush()

        with patch("evaluation.live_readiness.settings") as s:
            s.readiness_max_drawdown = 0.25
            result = self._run_check(db_session)
        assert result.status == "pass"

    def test_fail_on_extreme_drawdown(self, db_session):
        for bal in [1000.0, 500.0]:  # 50% drawdown
            db_session.add(BankrollLog(
                event_type="bet_settled",
                balance_after=bal,
                amount=0.0,
            ))
        db_session.flush()

        with patch("evaluation.live_readiness.settings") as s:
            s.readiness_max_drawdown = 0.25
            result = self._run_check(db_session)
        assert result.status == "fail"
        assert result.value == pytest.approx(0.5, abs=0.001)


# ---------------------------------------------------------------------------
# Test: ingestion health check
# ---------------------------------------------------------------------------

class TestIngestionHealthCheck:
    def _run_check(self, db):
        from evaluation.live_readiness import _check_ingestion_health
        return _check_ingestion_health(db, datetime.now(tz=timezone.utc))

    def test_pass_with_no_failures(self, db_session):
        result = self._run_check(db_session)
        assert result.status == "pass"
        assert result.value == 0

    def test_warn_on_few_failures(self, db_session):
        db_session.add(PipelineRun(
            job_name="ingest_afl",
            status="failed",
            daily_run_id=None,
            started_at=datetime.now(tz=timezone.utc),
        ))
        db_session.flush()

        with patch("evaluation.live_readiness.settings") as s:
            s.readiness_max_failed_jobs_7d = 2
            result = self._run_check(db_session)
        assert result.status == "warn"

    def test_fail_on_many_failures(self, db_session):
        for _ in range(5):
            db_session.add(PipelineRun(
                job_name="ingest_afl",
                status="failed",
                daily_run_id=None,
                started_at=datetime.now(tz=timezone.utc),
            ))
        db_session.flush()

        with patch("evaluation.live_readiness.settings") as s:
            s.readiness_max_failed_jobs_7d = 2
            result = self._run_check(db_session)
        assert result.status == "fail"
        assert result.value == 5


# ---------------------------------------------------------------------------
# Test: overall status derivation
# ---------------------------------------------------------------------------

class TestDeriveOverall:
    def _derive(self, statuses: list[str]) -> str:
        from evaluation.live_readiness import ReadinessCheck, _derive_overall
        checks = [ReadinessCheck(name=f"c{i}", status=s, detail="") for i, s in enumerate(statuses)]
        return _derive_overall(checks)

    def test_all_pass_is_ready(self):
        assert self._derive(["pass", "pass", "pass"]) == "ready"

    def test_one_warn_is_marginal(self):
        assert self._derive(["pass", "warn", "pass"]) == "marginal"

    def test_one_fail_is_not_ready(self):
        assert self._derive(["pass", "warn", "fail"]) == "not_ready"

    def test_all_warn_is_marginal(self):
        assert self._derive(["warn", "warn"]) == "marginal"

    def test_fail_overrides_warn(self):
        assert self._derive(["warn", "fail", "warn"]) == "not_ready"


# ---------------------------------------------------------------------------
# Test: critical TODOs check always returns fail if list is populated
# ---------------------------------------------------------------------------

class TestCriticalTodosCheck:
    def test_fail_when_todos_present(self):
        from evaluation.live_readiness import _check_critical_todos, CRITICAL_TODOS
        if not CRITICAL_TODOS:
            pytest.skip("No critical TODOs defined — check passes by design.")
        result = _check_critical_todos()
        assert result.status == "fail"
        assert result.value == len(CRITICAL_TODOS)

    def test_pass_when_todos_empty(self):
        from evaluation.live_readiness import _check_critical_todos
        with patch("evaluation.live_readiness.CRITICAL_TODOS", []):
            result = _check_critical_todos()
        assert result.status == "pass"
