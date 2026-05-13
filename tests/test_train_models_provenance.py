from __future__ import annotations

import json

import pandas as pd

from db.models.model_runs import ModelRun
from evaluation.evaluator import Evaluator
from models.base_model import BaseModel
from models.calibrated_model import CalibratedModel


class _DummyBaseModel(BaseModel):
    name = "dummy_model"
    version = "0.1"

    def fit(self, X: pd.DataFrame, y: pd.Series) -> None:
        self._fit_features = [col for col in X.columns if col.startswith("f")]

    def predict_proba(self, X: pd.DataFrame) -> pd.DataFrame:
        return pd.DataFrame(
            {
                "match_id": X["match_id"].values,
                "home_win_prob": [0.6] * len(X),
                "away_win_prob": [0.4] * len(X),
            }
        )

    def metadata(self) -> dict:
        return {**super().metadata(), "dummy": True}


def _frame(seasons: list[int]) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "match_id": list(range(1, len(seasons) + 1)),
            "season": seasons,
            "f1": [0.1 * i for i in range(1, len(seasons) + 1)],
            "f2": [0.2 * i for i in range(1, len(seasons) + 1)],
        }
    )


def test_build_model_run_metadata_contains_training_and_eval_ranges():
    from orchestration.jobs.train_models import _build_model_run_metadata

    model = _DummyBaseModel()
    train_df = _frame([2021, 2021, 2022])
    val_df = _frame([2023, 2023])
    cal_df = _frame([2022])
    model.fit(train_df, pd.Series([1, 0, 1]))

    metadata = _build_model_run_metadata(model, train_df, val_df, X_cal=cal_df)

    assert metadata["provenance_version"] == 1
    assert metadata["feature_names"] == ["f1", "f2"]
    assert metadata["n_features"] == 2
    assert metadata["train_from_season"] == 2021
    assert metadata["train_to_season"] == 2022
    assert metadata["evaluation_from_season"] == 2023
    assert metadata["evaluation_to_season"] == 2023
    assert metadata["calibration_from_season"] == 2022
    assert metadata["calibration_to_season"] == 2022


def test_train_and_record_uses_actual_calibrated_training_window(db_session, monkeypatch):
    from orchestration.jobs import train_models as tm

    monkeypatch.setattr(tm, "calibration_bins", lambda y_true, y_prob: [])
    monkeypatch.setattr(tm, "format_calibration_report", lambda bins, model_name: model_name)

    model = CalibratedModel(_DummyBaseModel())
    X_train = _frame([2021, 2022, 2022, 2023])
    y_train = pd.Series([1, 0, 1, 0])
    X_val = _frame([2024, 2024])
    y_val = pd.Series([1, 0])
    X_cal_train = _frame([2021, 2021, 2022])
    y_cal_train = pd.Series([1, 0, 1])
    X_cal = _frame([2023, 2023, 2023, 2023, 2023])
    y_cal = pd.Series([1, 0, 1, 0, 1])

    tm._train_and_record(
        db_session,
        model,
        X_train,
        y_train,
        X_val,
        y_val,
        Evaluator(),
        X_cal_train=X_cal_train,
        y_cal_train=y_cal_train,
        X_cal=X_cal,
        y_cal=y_cal,
    )
    db_session.flush()

    run = db_session.query(ModelRun).order_by(ModelRun.id.desc()).first()
    assert run is not None
    assert run.train_from_season == 2021
    assert run.train_to_season == 2022

    metadata = json.loads(run.metadata_json)
    assert metadata["calibrated_model"] is True
    assert metadata["train_from_season"] == 2021
    assert metadata["train_to_season"] == 2022
    assert metadata["evaluation_from_season"] == 2024
    assert metadata["calibration_from_season"] == 2023
    assert metadata["feature_names"] == ["f1", "f2"]
