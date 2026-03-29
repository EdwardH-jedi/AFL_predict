"""
db/models/daily_pipeline_runs.py
---------------------------------
Top-level record for each daily pipeline execution.

Each run groups all individual job PipelineRun rows.
One row per calendar date (UTC). Duplicate runs on the same day
(e.g. manual re-runs) generate a new row; the date column is NOT unique
so partial reruns can be tracked.
"""

import uuid
from datetime import date, datetime

from sqlalchemy import Date, DateTime, Float, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from db.base import Base


# Valid top-level pipeline statuses
PIPELINE_STATUSES = {"pending", "running", "success", "partial_failure", "failed"}


class DailyPipelineRun(Base):
    __tablename__ = "daily_pipeline_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    # Stable identifier for this run (useful in logs and artifact filenames)
    run_uuid: Mapped[str] = mapped_column(
        String(36), nullable=False, default=lambda: str(uuid.uuid4()), index=True
    )

    # Calendar date this run was intended to cover (UTC)
    run_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)

    # 'cron' | 'manual'
    triggered_by: Mapped[str] = mapped_column(String(20), nullable=False, default="manual")

    # pending | running | success | partial_failure | failed
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")

    started_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    duration_seconds: Mapped[float | None] = mapped_column(Float, nullable=True)

    # Human-readable notes (e.g. "manual rerun after stale odds")
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    def __repr__(self) -> str:
        return (
            f"<DailyPipelineRun id={self.id} date={self.run_date} "
            f"status={self.status!r} triggered_by={self.triggered_by!r}>"
        )
