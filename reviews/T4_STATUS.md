# T4 Status

## Changed

- Hardened `orchestration/jobs/train_models.py` so completed `ModelRun` rows now persist explicit `train_from_season` / `train_to_season`.
- Added provenance helpers in `train_models` to record the actual fitted training frame, including the calibrated-model case where fitting uses `X_cal_train` rather than the broader `X_train`.
- Expanded `metadata_json` written by `train_models` to include stable provenance fields:
  - `provenance_version`
  - `feature_names`
  - `n_features`
  - `fitted_on_rows`
  - `evaluated_on_rows`
  - `calibrated_model`
  - training / evaluation / calibration season ranges
  - `calibration_rows`
- Added focused tests in `tests/test_train_models_provenance.py`.

## Verified

- `python -m pytest tests\test_train_models_provenance.py -q` -> `2 passed`
- Verified that calibrated-model provenance uses the actual fit window (`X_cal_train`) when persisting `ModelRun` training-range fields.

## Remaining

- No full retrain was run in this slice.
- No backtest or broader recommendation-path rerun was performed in this slice.
- Any later provenance-based recommendation selection enhancements should build on this stronger `ModelRun` contract without reopening phase-1 logic.
