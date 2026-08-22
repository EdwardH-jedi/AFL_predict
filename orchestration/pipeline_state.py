"""
orchestration/pipeline_state.py
---------------------------------
Pipeline state machine helpers and retry wrapper.

Provides:
  - JobSpec  — static description of a pipeline job
  - JobResult — outcome of a single job execution
  - run_job_with_retry — executes a job module, retries on failure

Keeps all state logic here so daily_pipeline.py stays readable.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

from loguru import logger

from config.settings import get_settings

settings = get_settings()


@dataclass
class JobSpec:
    """Static configuration for one pipeline job."""

    name: str
    module: Any               # module with a run() function
    hard_dep: bool            # part of the critical chain (see requires)
    can_retry: bool = True    # if True, apply retry logic on failure
    # Names of jobs this one cannot run without. If any listed job did not
    # finish `success`, this job is skipped.
    #
    # Why this exists: `hard_dep` alone only ever skipped *later hard_dep jobs*,
    # so a build_features failure skipped nothing — generate_recommendations
    # still ran, against whatever features happened to be on disk. Naming the
    # upstream job makes the dependency real instead of implied by ordering.
    requires: tuple[str, ...] = ()
    # If True, a run that completes but reports zero records is reported
    # `degraded` rather than `success`. A missing API key or a provider outage
    # both look like "no exception raised, nothing ingested"; treating that as
    # success lets downstream jobs proceed on data that never arrived.
    expects_records: bool = False


@dataclass
class JobResult:
    """Outcome of one job execution attempt."""

    job_name: str
    # success           — completed and did the work
    # degraded          — completed but produced nothing where output was expected
    #                     (e.g. odds ingestion returning zero events because a key
    #                     is missing or the provider failed). Not a success: it
    #                     must not satisfy a downstream dependency.
    # partial_failure   — completed with some records rejected
    # failed | skipped  — as named
    status: str
    records_processed: int | None = None
    error_message: str | None = None
    duration_seconds: float | None = None
    retry_count: int = 0      # how many retries were consumed


def run_job_with_retry(spec: JobSpec) -> JobResult:
    """
    Execute spec.module.run(), retrying up to settings.pipeline_max_retries times.

    - Only retries if spec.can_retry is True.
    - On success returns status='success'.
    - On exhausted retries returns status='failed'.
    - If spec.expects_records is set and run() reports zero records, returns
      status='degraded' — the job did not raise, but it also did not deliver.
    - Does NOT raise — callers inspect JobResult.status.

    A job's run() may return an int record count (or None to opt out of the
    degraded check).
    """
    max_attempts = (settings.pipeline_max_retries + 1) if spec.can_retry else 1
    last_error: str | None = None
    attempts = 0

    for attempt in range(max_attempts):
        if attempt > 0:
            logger.warning(
                f"[{spec.name}] retry {attempt}/{settings.pipeline_max_retries} "
                f"after {settings.pipeline_retry_delay_seconds}s"
            )
            time.sleep(settings.pipeline_retry_delay_seconds)

        start = time.monotonic()
        try:
            records = spec.module.run()
            duration = time.monotonic() - start
            n = records if isinstance(records, int) else None

            if spec.expects_records and n == 0:
                logger.error(
                    f"[{spec.name}] completed in {duration:.1f}s but ingested 0 records "
                    "where output was expected — reporting DEGRADED. Check credentials "
                    "and provider availability; downstream jobs will be skipped."
                )
                return JobResult(
                    job_name=spec.name,
                    status="degraded",
                    records_processed=0,
                    error_message="Completed with zero records where records were expected.",
                    duration_seconds=round(duration, 2),
                    retry_count=attempt,
                )

            logger.info(f"[{spec.name}] succeeded in {duration:.1f}s (attempt {attempt + 1})")
            return JobResult(
                job_name=spec.name,
                status="success",
                records_processed=n,
                duration_seconds=round(duration, 2),
                retry_count=attempt,
            )
        except Exception as exc:
            attempts = attempt + 1
            last_error = str(exc)
            duration = time.monotonic() - start
            logger.error(f"[{spec.name}] attempt {attempt + 1} failed in {duration:.1f}s: {exc}")

    return JobResult(
        job_name=spec.name,
        status="failed",
        error_message=last_error,
        retry_count=attempts - 1,
    )
