"""Result leakage checks compare instants, including SQLite's naive UTC values."""

from datetime import UTC, datetime, timedelta, timezone

import pandas as pd
import pytest

from features import validators


class FixedDateTime(datetime):
    @classmethod
    def now(cls, tz=None):
        instant = cls(2026, 10, 29, 12, tzinfo=UTC)
        return instant.astimezone(tz) if tz else instant.replace(tzinfo=None)

    @classmethod
    def utcnow(cls):
        return cls(2026, 10, 29, 12)


@pytest.fixture(autouse=True)
def fixed_clock(monkeypatch):
    monkeypatch.setattr(validators, "datetime", FixedDateTime)


@pytest.mark.parametrize("hours", [-10, 0, 11])
@pytest.mark.parametrize("column", ["home_win", "home_score", "away_score", "result"])
def test_future_result_detected_regardless_of_offset(hours, column):
    kickoff = datetime(2026, 10, 29, 13, tzinfo=UTC).astimezone(
        timezone(timedelta(hours=hours))
    )
    assert len(validators.check_leakage({column: 1}, kickoff)) == 1


def test_settled_match_in_positive_offset_is_not_future():
    kickoff = datetime(2026, 10, 29, 11, tzinfo=UTC).astimezone(
        timezone(timedelta(hours=11))
    )
    assert validators.check_leakage({"home_win": 1}, kickoff) == []


def test_naive_sqlite_timestamp_is_utc():
    assert validators.check_leakage({"home_win": 1}, datetime(2026, 10, 29, 13))


@pytest.mark.parametrize("missing", [None, float("nan"), pd.NA])
def test_missing_result_is_not_leakage(missing):
    row = dict.fromkeys(["home_win", "home_score", "away_score", "result"], missing)
    assert validators.check_leakage(row, datetime(2026, 10, 29, 13, tzinfo=UTC)) == []
