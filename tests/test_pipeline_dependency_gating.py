"""
tests/test_pipeline_dependency_gating.py
-----------------------------------------
Guards that recommendations cannot be produced from stale or failed upstream
state (§7).

The defect: `hard_dep` only ever skipped *later hard_dep jobs*. Only the three
ingestion/feature jobs carried that flag and nothing hard-dep followed
`build_features`, so a feature-build failure skipped nothing —
`generate_recommendations` ran against whatever features happened to be on disk,
and `notify_bets` alerted on them.

Two mechanisms now cover it:
  requires        names the upstream jobs a job cannot run without
  degraded        a job that completes but ingests nothing where records were
                  expected does not count as success
"""

from __future__ import annotations

import types

from orchestration.pipeline_state import JobSpec, run_job_with_retry


def _module(fn):
    m = types.ModuleType("stub")
    m.run = fn
    return m


def _gate(specs: list[JobSpec], outcomes: dict[str, str]) -> dict[str, str]:
    """Replicate daily_pipeline's gating decision for a set of job outcomes.

    Mirrors the loop in orchestration/daily_pipeline.py::_execute_jobs so the
    dependency semantics can be asserted without standing up a database.
    """
    statuses: dict[str, str] = {}
    hard_dep_failed = False
    for spec in specs:
        unmet = [d for d in spec.requires if statuses.get(d) != "success"]
        if unmet:
            statuses[spec.name] = "skipped"
            continue
        if spec.hard_dep and hard_dep_failed:
            statuses[spec.name] = "skipped"
            continue
        statuses[spec.name] = outcomes.get(spec.name, "success")
        if statuses[spec.name] == "failed" and spec.hard_dep:
            hard_dep_failed = True
    return statuses


PIPELINE = [
    JobSpec(name="ingest_afl", module=None, hard_dep=True, expects_records=True),
    JobSpec(name="ingest_tab_odds", module=None, hard_dep=True, expects_records=True),
    JobSpec(name="build_features", module=None, hard_dep=True, can_retry=False),
    JobSpec(
        name="generate_recommendations", module=None, hard_dep=False, can_retry=False,
        requires=("build_features", "ingest_afl", "ingest_tab_odds"),
    ),
    JobSpec(
        name="notify_bets", module=None, hard_dep=False, can_retry=False,
        requires=("generate_recommendations",),
    ),
]


# ---------------------------------------------------------------------------
# The regression this exists for
# ---------------------------------------------------------------------------

def test_feature_build_failure_blocks_recommendations():
    """The exact scenario that previously skipped nothing."""
    s = _gate(PIPELINE, {"build_features": "failed"})
    assert s["build_features"] == "failed"
    assert s["generate_recommendations"] == "skipped", (
        "recommendations ran on stale features after the feature build failed"
    )
    assert s["notify_bets"] == "skipped"


def test_odds_ingestion_failure_blocks_recommendations():
    s = _gate(PIPELINE, {"ingest_tab_odds": "failed"})
    assert s["generate_recommendations"] == "skipped"
    assert s["notify_bets"] == "skipped"


def test_degraded_ingestion_does_not_satisfy_a_dependency():
    """Zero odds ingested is not a success, even though nothing raised."""
    s = _gate(PIPELINE, {"ingest_tab_odds": "degraded"})
    assert s["generate_recommendations"] == "skipped"


def test_partial_failure_does_not_satisfy_a_dependency():
    s = _gate(PIPELINE, {"build_features": "partial_failure"})
    assert s["generate_recommendations"] == "skipped"


def test_healthy_pipeline_runs_everything():
    s = _gate(PIPELINE, {})
    assert all(v == "success" for v in s.values()), s


def test_notify_is_blocked_transitively():
    """notify_bets depends on recommendations, which depend on features."""
    s = _gate(PIPELINE, {"build_features": "failed"})
    assert s["notify_bets"] == "skipped"


# ---------------------------------------------------------------------------
# degraded classification in run_job_with_retry
# ---------------------------------------------------------------------------

def test_zero_records_is_degraded_when_records_are_expected():
    spec = JobSpec(name="ingest", module=_module(lambda: 0), hard_dep=True,
                   can_retry=False, expects_records=True)
    result = run_job_with_retry(spec)
    assert result.status == "degraded"
    assert result.records_processed == 0


def test_zero_records_is_success_when_records_are_not_expected():
    """Jobs that legitimately no-op must not be penalised."""
    spec = JobSpec(name="maybe", module=_module(lambda: 0), hard_dep=False,
                   can_retry=False, expects_records=False)
    assert run_job_with_retry(spec).status == "success"


def test_records_are_recorded_on_success():
    spec = JobSpec(name="ingest", module=_module(lambda: 214), hard_dep=True,
                   can_retry=False, expects_records=True)
    result = run_job_with_retry(spec)
    assert result.status == "success"
    assert result.records_processed == 214


def test_job_returning_none_is_still_success():
    """Most jobs return nothing; they must not be treated as degraded."""
    spec = JobSpec(name="legacy", module=_module(lambda: None), hard_dep=False,
                   can_retry=False, expects_records=True)
    assert run_job_with_retry(spec).status == "success"


def test_raising_job_still_fails():
    def boom():
        raise RuntimeError("provider down")

    spec = JobSpec(name="ingest", module=_module(boom), hard_dep=True,
                   can_retry=False, expects_records=True)
    result = run_job_with_retry(spec)
    assert result.status == "failed"
    assert "provider down" in (result.error_message or "")


def test_real_pipeline_declares_the_dependencies():
    """The shipped registry, not just this test's copy, must carry them."""
    from orchestration.daily_pipeline import _ALL_JOBS

    by_name = {j.name: j for j in _ALL_JOBS}
    assert "build_features" in by_name["generate_recommendations"].requires
    assert "ingest_tab_odds" in by_name["generate_recommendations"].requires
    assert "generate_recommendations" in by_name["notify_bets"].requires
    assert by_name["ingest_afl"].expects_records
    assert by_name["ingest_tab_odds"].expects_records
