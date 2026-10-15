from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock

from db.models.daily_pipeline_runs import DailyPipelineRun
from db.models.matches import Match
from db.models.odds_snapshots import OddsSnapshot
from db.models.pipeline_runs import PipelineRun


def test_upcoming_without_odds_focuses_on_actionable_window(db_session):
    from orchestration.jobs.check_data_freshness import _upcoming_without_odds

    now = datetime(2026, 4, 18, 3, 0, tzinfo=UTC)
    soon_match = Match(
        season=2026,
        round_number=7,
        home_team_id=1,
        away_team_id=2,
        match_time=(now + timedelta(days=2)).replace(tzinfo=None),
        result=None,
    )
    far_match = Match(
        season=2026,
        round_number=12,
        home_team_id=3,
        away_team_id=4,
        match_time=(now + timedelta(days=21)).replace(tzinfo=None),
        result=None,
    )
    covered_match = Match(
        season=2026,
        round_number=7,
        home_team_id=5,
        away_team_id=6,
        match_time=(now + timedelta(days=1)).replace(tzinfo=None),
        result=None,
    )
    db_session.add_all([soon_match, far_match, covered_match])
    db_session.flush()
    db_session.add(
        OddsSnapshot(
            match_id=covered_match.id,
            bookmaker="TAB",
            home_odds=1.8,
            away_odds=2.0,
            home_implied_prob=0.53,
            away_implied_prob=0.47,
            overround=1.0,
            snapshot_time=now.replace(tzinfo=None),
            snapshot_type="scheduled",
        )
    )
    db_session.commit()

    result = _upcoming_without_odds(db_session, now)

    assert result["actionable_count"] == 1
    assert result["total_missing"] == 2
    assert result["examples"] == [
        {
            "match_id": soon_match.id,
            "season": 2026,
            "round_number": 7,
            "match_time": soon_match.match_time.isoformat(),
            "home_team_id": 1,
            "away_team_id": 2,
        }
    ]


def test_pipeline_status_uses_final_persisted_job_states(db_session):
    from orchestration.jobs.generate_daily_summary import _pipeline_status

    today = date(2026, 4, 18)
    daily_run = DailyPipelineRun(
        run_date=today,
        triggered_by="cron",
        status="success",
        started_at=datetime(2026, 4, 18, 3, 21, tzinfo=UTC),
        completed_at=datetime(2026, 4, 18, 3, 22, tzinfo=UTC),
        duration_seconds=13.5,
    )
    db_session.add(daily_run)
    db_session.flush()
    db_session.add_all(
        [
            PipelineRun(
                daily_run_id=daily_run.id,
                job_name="ingest_afl",
                status="success",
                duration_seconds=3.2,
            ),
            PipelineRun(
                daily_run_id=daily_run.id,
                job_name="generate_daily_summary",
                status="success",
                duration_seconds=0.2,
            ),
        ]
    )
    db_session.commit()

    payload = _pipeline_status(db_session, today)

    assert payload["status"] == "success"
    assert payload["completed_at"] is not None
    assert [job["status"] for job in payload["jobs"]] == ["success", "success"]


def test_refresh_daily_summary_artifact_rewrites_after_completion(monkeypatch):
    from orchestration import daily_pipeline

    set_run_id = MagicMock()
    write_summary = MagicMock(return_value=Path("storage/daily_summaries/2026-04-18.json"))

    monkeypatch.setattr(daily_pipeline.generate_daily_summary, "set_daily_run_id", set_run_id)
    monkeypatch.setattr(
        daily_pipeline.generate_daily_summary,
        "write_summary_artifact",
        write_summary,
    )

    daily_pipeline._refresh_daily_summary_artifact(42)

    set_run_id.assert_called_once_with(42)
    write_summary.assert_called_once_with()
