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
    hard_dep: bool            # if True, failure aborts subsequent hard-dep jobs
    can_retry: bool = True    # if True, apply retry logic on failure


@dataclass
class JobResult:
    """Outcome of one job execution attempt."""

    job_name: str
    status: str               # success | partial_failure | failed | skipped
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
    - Does NOT raise — callers inspect JobResult.status.
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
            spec.module.run()
            duration = time.monotonic() - start
            logger.info(f"[{spec.name}] succeeded in {duration:.1f}s (attempt {attempt + 1})")
            return JobResult(
                job_name=spec.name,
                status="success",
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
