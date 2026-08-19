"""
tests/test_pipeline_orchestration.py
--------------------------------------
Tests for pipeline state machine, retry logic, and orchestration flow.

Uses lightweight mock job modules to avoid real DB/network calls.
"""

from __future__ import annotations

import types
from unittest.mock import MagicMock, patch

from orchestration.pipeline_state import JobResult, JobSpec, run_job_with_retry

# ---------------------------------------------------------------------------
# Helpers: mock job modules
# ---------------------------------------------------------------------------

def _make_job_module(fail_times: int = 0) -> types.ModuleType:
    """
    Create a mock job module whose run() raises ValueError the first
    `fail_times` calls, then succeeds.
    """
    call_count = {"n": 0}

    def run():
        call_count["n"] += 1
        if call_count["n"] <= fail_times:
            raise ValueError(f"Simulated failure #{call_count['n']}")

    mod = types.ModuleType("mock_job")
    mod.run = run
    return mod


def _make_always_failing_job() -> types.ModuleType:
    mod = types.ModuleType("always_fail")
    mod.run = MagicMock(side_effect=RuntimeError("permanent failure"))
    return mod


# ---------------------------------------------------------------------------
# JobSpec / run_job_with_retry tests
# ---------------------------------------------------------------------------

class TestRunJobWithRetry:
    def test_success_on_first_attempt(self):
        mod = _make_job_module(fail_times=0)
        spec = JobSpec(name="test_job", module=mod, hard_dep=False, can_retry=True)

        with patch("orchestration.pipeline_state.settings") as s:
            s.pipeline_max_retries = 2
            s.pipeline_retry_delay_seconds = 0.0
            result = run_job_with_retry(spec)

        assert result.status == "success"
        assert result.retry_count == 0
        assert result.error_message is None

    def test_success_after_one_retry(self):
        mod = _make_job_module(fail_times=1)
        spec = JobSpec(name="test_retry", module=mod, hard_dep=False, can_retry=True)

        with patch("orchestration.pipeline_state.settings") as s:
            s.pipeline_max_retries = 2
            s.pipeline_retry_delay_seconds = 0.0
            result = run_job_with_retry(spec)

        assert result.status == "success"
        assert result.retry_count == 1

    def test_fail_after_exhausted_retries(self):
        mod = _make_always_failing_job()
        spec = JobSpec(name="always_fail", module=mod, hard_dep=False, can_retry=True)

        with patch("orchestration.pipeline_state.settings") as s:
            s.pipeline_max_retries = 2
            s.pipeline_retry_delay_seconds = 0.0
            result = run_job_with_retry(spec)

        assert result.status == "failed"
        assert "permanent failure" in result.error_message
        assert result.retry_count == 2  # 2 retries consumed

    def test_no_retry_when_can_retry_false(self):
        mod = _make_always_failing_job()
        spec = JobSpec(name="no_retry", module=mod, hard_dep=False, can_retry=False)

        with patch("orchestration.pipeline_state.settings") as s:
            s.pipeline_max_retries = 3
            s.pipeline_retry_delay_seconds = 0.0
            result = run_job_with_retry(spec)

        assert result.status == "failed"
        assert result.retry_count == 0
        assert mod.run.call_count == 1

    def test_duration_recorded_on_success(self):
        mod = _make_job_module(fail_times=0)
        spec = JobSpec(name="timed", module=mod, hard_dep=False, can_retry=False)

        with patch("orchestration.pipeline_state.settings") as s:
            s.pipeline_max_retries = 0
            s.pipeline_retry_delay_seconds = 0.0
            result = run_job_with_retry(spec)

        assert result.duration_seconds is not None
        assert result.duration_seconds >= 0.0


# ---------------------------------------------------------------------------
# _derive_overall_status tests (via orchestrator module)
# ---------------------------------------------------------------------------

class TestDeriveOverallStatus:
    """Test the pipeline-level status derivation logic."""

    def setup_method(self):
        from orchestration import daily_pipeline
        self._fn = daily_pipeline._derive_overall_status

    def test_all_success(self):
        results = [
            JobResult("ingest_afl", "success"),
            JobResult("build_features", "success"),
            JobResult("generate_recommendations", "success"),
        ]
        assert self._fn(results) == "success"

    def test_soft_job_fail_gives_partial(self):
        results = [
            JobResult("ingest_afl", "success"),
            JobResult("build_features", "success"),
            JobResult("generate_recommendations", "failed"),  # soft job
        ]
        assert self._fn(results) == "partial_failure"

    def test_hard_dep_fail_gives_failed(self):
        results = [
            JobResult("ingest_afl", "failed"),
            JobResult("build_features", "skipped"),
        ]
        assert self._fn(results) == "failed"

    def test_skipped_only_is_success(self):
        # If all downstream jobs were skipped but orchestrator marks hard dep failed,
        # the overall should be failed (the hard dep itself is in the list)
        results = [
            JobResult("ingest_afl", "failed"),
            JobResult("ingest_tab_odds", "skipped"),
            JobResult("build_features", "skipped"),
        ]
        assert self._fn(results) == "failed"

    def test_mixed_with_no_hard_dep_fail(self):
        """Soft failures with all hard deps succeeding → partial_failure."""
        results = [
            JobResult("ingest_afl", "success"),
            JobResult("ingest_tab_odds", "success"),
            JobResult("build_features", "success"),
            JobResult("generate_recommendations", "failed"),
            JobResult("settle_results", "failed"),
        ]
        assert self._fn(results) == "partial_failure"


# ---------------------------------------------------------------------------
# Pipeline state constants
# ---------------------------------------------------------------------------

class TestPipelineConstants:
    def test_job_statuses_defined(self):
        from db.models.pipeline_runs import JOB_STATUSES
        assert "pending" in JOB_STATUSES
        assert "running" in JOB_STATUSES
        assert "success" in JOB_STATUSES
        assert "partial_failure" in JOB_STATUSES
        assert "failed" in JOB_STATUSES
        assert "skipped" in JOB_STATUSES

    def test_pipeline_statuses_defined(self):
        from db.models.daily_pipeline_runs import PIPELINE_STATUSES
        assert "success" in PIPELINE_STATUSES
        assert "failed" in PIPELINE_STATUSES
        assert "partial_failure" in PIPELINE_STATUSES

    def test_daily_jobs_list_has_expected_jobs(self):
        from orchestration.daily_pipeline import DAILY_JOBS
        names = [j.name for j in DAILY_JOBS]
        assert "ingest_afl" in names
        assert "ingest_tab_odds" in names
        assert "build_features" in names
        assert "generate_recommendations" in names
        assert "settle_results" in names
        assert "generate_daily_summary" in names
        assert "check_data_freshness" in names

    def test_ingest_jobs_are_retryable(self):
        from orchestration.daily_pipeline import DAILY_JOBS
        retryable = {j.name for j in DAILY_JOBS if j.can_retry}
        assert "ingest_afl" in retryable
        assert "ingest_tab_odds" in retryable

    def test_hard_dep_jobs(self):
        from orchestration.daily_pipeline import DAILY_JOBS
        hard = {j.name for j in DAILY_JOBS if j.hard_dep}
        assert "ingest_afl" in hard
        assert "build_features" in hard
        # Soft jobs should NOT be hard deps
        soft = {j.name for j in DAILY_JOBS if not j.hard_dep}
        assert "generate_recommendations" in soft
        assert "generate_daily_summary" in soft
