"""
orchestration/daily_pipeline.py
---------------------------------
Daily pipeline orchestrator with explicit state tracking, retry support,
stale-data detection, and daily summary artifact generation.

Pipeline run states:
  pending        — job created, not yet started
  running        — job is actively executing
  success        — job completed with no errors
  partial_failure — job completed but with non-critical warnings
  failed         — job raised an unrecoverable error
  skipped        — job was not attempted (hard-dep upstream failed)

The top-level DailyPipelineRun status reflects the worst job outcome:
  all success              → success
  any soft-job failed      → partial_failure
  any hard-dep failed      → failed

Usage:
    python -m orchestration.daily_pipeline
    python -m orchestration.daily_pipeline --triggered-by cron
    make pipeline
"""

from __future__ import annotations

import argparse
import sys
import time
from datetime import UTC, date, datetime

from loguru import logger

from config.settings import get_settings
from db.models.daily_pipeline_runs import DailyPipelineRun
from db.models.pipeline_runs import PipelineRun
from db.session import db_session
from orchestration.jobs import (
    build_features,
    check_data_freshness,
    generate_daily_summary,
    generate_recommendations,
    ingest_afl,
    ingest_tab_odds,
    notify_bets,
    settle_results,
)
from orchestration.jobs.roles import (
    data_steward as role_data_steward,
)
from orchestration.jobs.roles import (
    feature_engineer as role_feature_engineer,
)
from orchestration.jobs.roles import (
    model_engineer as role_model_engineer,
)
from orchestration.jobs.roles import (
    quant_reviewer as role_quant_reviewer,
)
from orchestration.jobs.roles import (
    risk_manager as role_risk_manager,
)
from orchestration.pipeline_state import JobResult, JobSpec, run_job_with_retry

settings = get_settings()

# ---------------------------------------------------------------------------
# Job registry
# ---------------------------------------------------------------------------
# Order matters. hard_dep=True means a failure in this job will cause all
# subsequent hard_dep jobs to be skipped.
#
# NODE_ROLE filtering (set NODE_ROLE in .env):
#   standalone  — all jobs (default, single-machine)
#   collector   — ingestion only: freshness check + ingest_afl + ingest_tab_odds + summary
#   predictor   — modelling only: build_features + recommendations + settle + summary

_ALL_JOBS: list[JobSpec] = [
    # Pre-flight: data freshness check (soft — never blocks the pipeline)
    JobSpec(
        name="check_data_freshness",
        module=check_data_freshness,
        hard_dep=False,
        can_retry=False,
    ),

    # Ingestion (hard deps — recommendations are meaningless without fresh data)
    JobSpec(name="ingest_afl", module=ingest_afl, hard_dep=True, can_retry=True),
    JobSpec(name="ingest_tab_odds", module=ingest_tab_odds, hard_dep=True, can_retry=True),

    # Feature build (hard dep — predictions require features)
    JobSpec(name="build_features", module=build_features, hard_dep=True, can_retry=False),

    # Downstream (soft — stale or empty output is unfortunate but not fatal)
    JobSpec(
        name="generate_recommendations",
        module=generate_recommendations,
        hard_dep=False,
        can_retry=False,
    ),
    JobSpec(name="notify_bets", module=notify_bets, hard_dep=False, can_retry=False),
    JobSpec(name="settle_results", module=settle_results, hard_dep=False, can_retry=False),

    # Summary artifact (soft — failure just means no JSON file for today)
    JobSpec(
        name="generate_daily_summary",
        module=generate_daily_summary,
        hard_dep=False,
        can_retry=False,
    ),

    # Role audits (all soft, all read-only, all produce per-role JSON artifacts
    # under storage/daily_summaries/roles/). Order mirrors the dependency chain:
    # data → features → models → risk → reviewer.
    JobSpec(
        name="role_data_steward",
        module=role_data_steward,
        hard_dep=False,
        can_retry=False,
    ),
    JobSpec(
        name="role_feature_engineer",
        module=role_feature_engineer,
        hard_dep=False,
        can_retry=False,
    ),
    JobSpec(
        name="role_model_engineer",
        module=role_model_engineer,
        hard_dep=False,
        can_retry=False,
    ),
    JobSpec(
        name="role_risk_manager",
        module=role_risk_manager,
        hard_dep=False,
        can_retry=False,
    ),
    JobSpec(
        name="role_quant_reviewer",
        module=role_quant_reviewer,
        hard_dep=False,
        can_retry=False,
    ),
]

# Jobs run on the collector machine (RX 6600): ingestion + freshness + summary
# Data Steward audit also runs here — it reports on source coverage, which is
# the collector's responsibility.
_COLLECTOR_JOB_NAMES = {
    "check_data_freshness",
    "ingest_afl",
    "ingest_tab_odds",
    "generate_daily_summary",
    "role_data_steward",
}

# Jobs run on the predictor machine (RTX 5080): feature build + modelling + summary
# All five role audits run on the predictor — that is where models, features,
# recommendations, and evaluation state all live.
_PREDICTOR_JOB_NAMES = {
    "build_features",
    "generate_recommendations",
    "notify_bets",
    "settle_results",
    "generate_daily_summary",
    "role_data_steward",
    "role_feature_engineer",
    "role_model_engineer",
    "role_risk_manager",
    "role_quant_reviewer",
}


def _build_job_list(role: str) -> list[JobSpec]:
    """Return the subset of jobs that should run for the given NODE_ROLE."""
    if role == "collector":
        return [j for j in _ALL_JOBS if j.name in _COLLECTOR_JOB_NAMES]
    if role == "predictor":
        return [j for j in _ALL_JOBS if j.name in _PREDICTOR_JOB_NAMES]
    return list(_ALL_JOBS)  # standalone: all jobs


DAILY_JOBS: list[JobSpec] = _build_job_list(settings.node_role)


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------

def run_pipeline(triggered_by: str = "manual") -> bool:
    """
    Execute all daily jobs in order, persisting state to the database.

    Args:
        triggered_by: 'cron' | 'manual' — stored on the DailyPipelineRun record.

    Returns:
        True if overall status is 'success', False for partial_failure or failed.
    """
    wall_start = time.monotonic()
    today = date.today()
    logger.info(
        f"========== Daily pipeline starting [{today}] triggered_by={triggered_by} =========="
    )

    # Create top-level daily run record
    with db_session() as db:
        daily_run = DailyPipelineRun(
            run_date=today,
            triggered_by=triggered_by,
            status="running",
            started_at=datetime.now(tz=UTC),
        )
        db.add(daily_run)
        db.flush()
        daily_run_id = daily_run.id
        logger.info(f"DailyPipelineRun id={daily_run_id} uuid={daily_run.run_uuid}")

    # Inform summary job which run record to reference
    generate_daily_summary.set_daily_run_id(daily_run_id)

    # Execute jobs
    results: list[JobResult] = _execute_jobs(daily_run_id)

    # Determine overall status
    overall_status = _derive_overall_status(results)

    # Persist final daily run state
    wall_duration = time.monotonic() - wall_start
    with db_session() as db:
        daily_run = db.get(DailyPipelineRun, daily_run_id)
        if daily_run:
            daily_run.status = overall_status
            daily_run.completed_at = datetime.now(tz=UTC)
            daily_run.duration_seconds = round(wall_duration, 2)

    _refresh_daily_summary_artifact(daily_run_id)

    logger.info(
        f"========== Daily pipeline {overall_status.upper()} "
        f"in {wall_duration:.1f}s ==========\n"
        + _format_job_summary(results)
    )
    return overall_status == "success"


def _execute_jobs(daily_run_id: int) -> list[JobResult]:
    """
    Run all jobs in order, skipping hard-dep jobs after a hard-dep failure.

    Each job gets its own PipelineRun row written to the database.
    """
    results: list[JobResult] = []
    hard_dep_failed = False

    for spec in DAILY_JOBS:
        # Check if this job should be skipped
        if spec.hard_dep and hard_dep_failed:
            result = JobResult(
                job_name=spec.name,
                status="skipped",
                error_message="Skipped: upstream hard dependency failed.",
            )
            _persist_job_run(daily_run_id, spec.name, result)
            results.append(result)
            logger.info(f"[{spec.name}] SKIPPED (hard-dep chain broken)")
            continue

        # Run the job (with retry if configured)
        logger.info(f"[{spec.name}] starting ...")
        _write_pending_job_run(daily_run_id, spec.name)

        result = run_job_with_retry(spec)
        _persist_job_run(daily_run_id, spec.name, result)
        results.append(result)

        if result.status == "failed" and spec.hard_dep:
            hard_dep_failed = True
            logger.error(
                f"[{spec.name}] HARD DEPENDENCY FAILED — "
                "subsequent hard-dep jobs will be skipped."
            )

    return results


def _write_pending_job_run(daily_run_id: int, job_name: str) -> None:
    """Pre-create a PipelineRun row in 'running' state before the job starts."""
    with db_session() as db:
        row = PipelineRun(
            daily_run_id=daily_run_id,
            job_name=job_name,
            status="running",
            started_at=datetime.now(tz=UTC),
        )
        db.add(row)


def _persist_job_run(daily_run_id: int, job_name: str, result: JobResult) -> None:
    """Update the most recent running PipelineRun for this job with final state."""
    with db_session() as db:
        # Find the most recent running row for this job/daily_run
        row: PipelineRun | None = (
            db.query(PipelineRun)
            .filter(
                PipelineRun.daily_run_id == daily_run_id,
                PipelineRun.job_name == job_name,
            )
            .order_by(PipelineRun.id.desc())
            .first()
        )
        if row is None:
            # Skipped jobs may not have a pre-created row — create one now
            row = PipelineRun(
                daily_run_id=daily_run_id,
                job_name=job_name,
                started_at=datetime.now(tz=UTC),
            )
            db.add(row)

        row.status = result.status
        row.completed_at = datetime.now(tz=UTC)
        row.duration_seconds = result.duration_seconds
        row.records_processed = result.records_processed
        row.retry_count = result.retry_count
        row.error_message = result.error_message


def _derive_overall_status(results: list[JobResult]) -> str:
    """
    Determine top-level status from individual job results.

      all success           → "success"
      any hard-dep failed   → "failed"
      any soft job failed   → "partial_failure"
      only skips + success  → "success" (hard dep failed in prev run, but this run was clean)
    """
    hard_dep_names = {spec.name for spec in DAILY_JOBS if spec.hard_dep}

    for r in results:
        if r.status == "failed" and r.job_name in hard_dep_names:
            return "failed"

    has_any_failure = any(r.status == "failed" for r in results)
    if has_any_failure:
        return "partial_failure"

    return "success"


def _format_job_summary(results: list[JobResult]) -> str:
    lines = ["Job results:"]
    for r in results:
        retry_note = f" (retried {r.retry_count}x)" if r.retry_count else ""
        dur = f" {r.duration_seconds:.1f}s" if r.duration_seconds is not None else ""
        err = f" — {r.error_message}" if r.error_message else ""
        lines.append(f"  {r.job_name:<30} {r.status.upper()}{retry_note}{dur}{err}")
    return "\n".join(lines)


def _refresh_daily_summary_artifact(daily_run_id: int) -> None:
    """
    Rewrite today's daily summary after final job states are persisted.

    The summary job runs before the orchestrator knows the final pipeline
    status, so this post-pass keeps the operator artifact aligned with the
    finished run state.
    """
    try:
        generate_daily_summary.set_daily_run_id(daily_run_id)
        path = generate_daily_summary.write_summary_artifact()
        logger.info(f"Refreshed final daily summary artifact at {path}")
    except Exception:
        logger.exception("Failed to refresh final daily summary artifact")


# ---------------------------------------------------------------------------
# Class wrapper (for import compatibility)
# ---------------------------------------------------------------------------


class DailyPipeline:
    """Thin wrapper around run_pipeline() for import compatibility."""

    def run(self, triggered_by: str = "manual") -> bool:
        return run_pipeline(triggered_by=triggered_by)


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run the AFL daily pipeline.")
    parser.add_argument(
        "--triggered-by",
        default="manual",
        choices=["manual", "cron"],
        help="Source that triggered this run (stored in DB).",
    )
    args = parser.parse_args()

    success = run_pipeline(triggered_by=args.triggered_by)
    sys.exit(0 if success else 1)
