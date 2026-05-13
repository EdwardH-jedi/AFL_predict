"""tests/test_alembic_fresh_db.py

Smoke test: a freshly-cloned checkout pointed at an empty SQLite database
must be able to bring the schema up to head via `alembic upgrade head`.

This test guards against future migrations that assume the base schema
already exists. It runs Alembic in a subprocess so settings/env caching
in this Python process is not affected, and so the test mirrors what a
new operator actually types after cloning the repo.
"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest
from sqlalchemy import create_engine, inspect

REPO_ROOT = Path(__file__).resolve().parent.parent

# Core tables required by the documented project layout. If any of these
# disappear after `alembic upgrade head`, the fresh-clone setup is broken.
REQUIRED_TABLES = {
    "matches",
    "teams",
    "predictions",
    "recommendations",
    "model_runs",
    "bet_outcomes",
    "bankroll_logs",
}


def _run_alembic_upgrade_head(db_path: Path) -> subprocess.CompletedProcess[str]:
    """Run `alembic upgrade head` in a subprocess against ``db_path``."""
    env = os.environ.copy()
    env["DB_URL"] = f"sqlite:///{db_path.as_posix()}"
    # Defensive defaults so config.settings does not fail to load.
    env.setdefault("API_SECRET_KEY", "test-secret")
    env.setdefault("APP_ENV", "development")
    return subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=str(REPO_ROOT),
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )


@pytest.mark.slow
def test_alembic_upgrade_head_on_empty_sqlite_db() -> None:
    """`alembic upgrade head` must succeed against an empty SQLite file
    and leave all required core tables in place."""
    with tempfile.TemporaryDirectory() as tmp:
        db_path = Path(tmp) / "fresh_clone_smoketest.db"
        assert not db_path.exists(), "tempdir should start empty"

        result = _run_alembic_upgrade_head(db_path)
        assert result.returncode == 0, (
            "alembic upgrade head failed on a fresh empty SQLite DB.\n"
            f"stdout:\n{result.stdout}\n"
            f"stderr:\n{result.stderr}"
        )
        assert db_path.exists(), "expected SQLite DB file to be created"

        engine = create_engine(f"sqlite:///{db_path.as_posix()}")
        try:
            present = set(inspect(engine).get_table_names())
        finally:
            engine.dispose()

        missing = REQUIRED_TABLES - present
        assert not missing, (
            f"core tables missing after upgrade head: {sorted(missing)}\n"
            f"tables present: {sorted(present)}"
        )

        # alembic_version must reflect that the DB is at head.
        engine = create_engine(f"sqlite:///{db_path.as_posix()}")
        try:
            with engine.connect() as conn:
                row = conn.exec_driver_sql(
                    "SELECT version_num FROM alembic_version"
                ).fetchone()
        finally:
            engine.dispose()
        assert row is not None, "alembic_version row missing"
