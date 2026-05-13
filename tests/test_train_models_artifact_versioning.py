"""Artifact-versioning contract for train_models.

Each ModelRun must write into its own immutable subdirectory so consecutive
training runs cannot overwrite earlier artifacts. The load path
(generate_recommendations._instantiate_model) uses Path(artifact_path).parent,
so legacy rows pointing at flat <ARTIFACTS_DIR>/<name>_<version>.pkl must
keep loading too.
"""
from __future__ import annotations

from datetime import UTC, datetime

import pandas as pd

from models.bookmaker_baseline import BookmakerBaseline
from models.elo_baseline import EloBaseline


def _fit_elo(seed_home: int, seed_away: int) -> EloBaseline:
    """Return a quickly-fitted EloBaseline whose ratings depend on the inputs."""
    model = EloBaseline()
    X = pd.DataFrame(
        {
            "match_id": [1],
            "season": [2025],
            "home_team_id": [seed_home],
            "away_team_id": [seed_away],
        }
    )
    model.fit(X, pd.Series([1]))
    return model


def test_save_artifact_for_run_yields_unique_paths_and_keeps_prior_runs(tmp_path, monkeypatch):
    from orchestration.jobs import train_models as tm

    monkeypatch.setattr(tm, "ARTIFACTS_DIR", tmp_path)

    path1 = tm._save_artifact_for_run(
        _fit_elo(1, 2),
        run_id=1,
        ts=datetime(2026, 5, 13, 12, 0, 0, tzinfo=UTC),
    )
    path2 = tm._save_artifact_for_run(
        _fit_elo(3, 4),
        run_id=2,
        ts=datetime(2026, 5, 13, 13, 0, 0, tzinfo=UTC),
    )

    assert path1 is not None
    assert path2 is not None
    # Same filename pattern, different parent directory — keeps
    # model.load(artifact_path.parent) working unchanged.
    assert path1.name == path2.name == "elo_baseline_0.1.pkl"
    assert path1 != path2
    assert path1.parent != path2.parent
    assert path1.exists(), "first run's artifact must survive a second run"
    assert path2.exists()


def test_save_artifact_for_run_returns_none_for_stateless_model(tmp_path, monkeypatch):
    from orchestration.jobs import train_models as tm

    monkeypatch.setattr(tm, "ARTIFACTS_DIR", tmp_path)

    saved = tm._save_artifact_for_run(
        BookmakerBaseline(),
        run_id=99,
        ts=datetime(2026, 5, 13, 14, 0, 0, tzinfo=UTC),
    )
    assert saved is None
    # No empty per-run directory left behind for the stateless model.
    leftovers = [p for p in tmp_path.iterdir() if p.is_dir() and p.name.startswith("run_99_")]
    assert leftovers == []


def test_load_uses_artifact_path_parent_for_new_layout(tmp_path, monkeypatch):
    """Mirror generate_recommendations._instantiate_model: load via .parent."""
    from orchestration.jobs import train_models as tm

    monkeypatch.setattr(tm, "ARTIFACTS_DIR", tmp_path)

    original = _fit_elo(7, 8)
    path = tm._save_artifact_for_run(
        original,
        run_id=42,
        ts=datetime(2026, 5, 13, 15, 0, 0, tzinfo=UTC),
    )
    assert path is not None

    reloaded = EloBaseline()
    reloaded.load(path.parent)
    assert reloaded.ratings == original.ratings


def test_legacy_static_artifact_path_still_loads(tmp_path):
    """Existing ModelRun rows with the old flat layout must keep working."""
    original = _fit_elo(11, 12)
    legacy_path = original.save(tmp_path)

    assert legacy_path.name == "elo_baseline_0.1.pkl"
    assert legacy_path.parent == tmp_path

    reloaded = EloBaseline()
    reloaded.load(legacy_path.parent)
    assert reloaded.ratings == original.ratings
