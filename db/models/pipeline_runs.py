"""db/models/pipeline_runs.py — Audit log for each individual pipeline job execution."""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from db.base import Base


# Valid job-level status values
JOB_STATUSES = {"pending", "running", "success", "partial_failure", "failed", "skipped"}


class PipelineRun(Base):
    __tablename__ = "pipeline_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    # Links to the parent daily run (nullable for legacy rows)
    daily_run_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("daily_pipeline_runs.id"), nullable=True, index=True
    )

    # Name of the job, e.g. 'ingest_afl', 'build_features'
    job_name: Mapped[str] = mapped_column(String(100), nullable=False, index=True)

    # pending | running | success | partial_failure | failed | skipped
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")

    started_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    # Duration in seconds (filled on completion)
    duration_seconds: Mapped[float | None] = mapped_column(Float, nullable=True)

    # Count of records processed (meaning varies by job)
    records_processed: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # Number of retry attempts consumed (0 = first try succeeded)
    retry_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    def __repr__(self) -> str:
        return (
            f"<PipelineRun id={self.id} job={self.job_name!r} "
            f"status={self.status!r} retries={self.retry_count}>"
        )
