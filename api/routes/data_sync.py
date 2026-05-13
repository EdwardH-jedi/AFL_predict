"""
api/routes/data_sync.py
------------------------
Sync endpoints for the dual-machine (collector ↔ predictor) architecture.

These endpoints are served by the **collector** machine (RX 6600) and consumed
by the **predictor** machine (RTX 5080).

Data flow:
  1. Predictor calls GET /api/sync/latest-odds    → pulls latest bookmaker odds
  2. Predictor calls GET /api/sync/latest-features → pulls latest feature parquet
  3. Predictor runs models and calls POST /api/sync/predictions → pushes results back

Authentication:
  All endpoints require the `X-Sync-Token` header to match api_secret_key from
  settings. Set the same API_SECRET_KEY on both machines.

Usage (predictor side):
    curl -H "X-Sync-Token: <secret>" http://rx6600:8000/api/sync/latest-odds
    curl -H "X-Sync-Token: <secret>" http://rx6600:8000/api/sync/latest-features -o features.parquet
    curl -H "X-Sync-Token: <secret>" -X POST http://rx6600:8000/api/sync/predictions \\
         -H "Content-Type: application/json" -d '{"predictions": [...]}'
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated

import pandas as pd
from fastapi import APIRouter, Depends, Header, HTTPException, status
from fastapi.responses import FileResponse, JSONResponse
from loguru import logger
from pydantic import BaseModel, Field

from config.settings import get_settings

router = APIRouter()
settings = get_settings()


# ---------------------------------------------------------------------------
# Auth dependency
# ---------------------------------------------------------------------------

def _require_sync_token(x_sync_token: Annotated[str | None, Header()] = None) -> None:
    """Reject requests with a missing or incorrect sync token."""
    if (
        not settings.api_secret_key
        or settings.api_secret_key == "changeme-use-a-long-random-string"
    ):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Sync endpoints unavailable: api_secret_key is not configured.",
        )
    if x_sync_token != settings.api_secret_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing X-Sync-Token header.",
        )


# ---------------------------------------------------------------------------
# GET /api/sync/latest-odds
# ---------------------------------------------------------------------------

@router.get(
    "/latest-odds",
    summary="Pull latest bookmaker odds snapshot",
    dependencies=[Depends(_require_sync_token)],
)
def get_latest_odds() -> JSONResponse:
    """
    Return the most recently captured bookmaker odds snapshot as JSON.

    The predictor machine calls this to obtain the odds data it needs for
    recommendation generation, without requiring direct DB access.
    """
    snapshots_dir = Path(settings.raw_snapshots_dir) / "odds"
    files = sorted(
        snapshots_dir.glob("odds*.json"),
        key=lambda p: p.stat().st_mtime,
    ) if snapshots_dir.exists() else []

    if not files:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No odds snapshot files found in {snapshots_dir}.",
        )

    latest = files[-1]
    logger.info(f"sync: serving odds snapshot {latest.name}")

    try:
        with open(latest, encoding="utf-8") as f:
            data = json.load(f)
    except Exception as exc:
        logger.error(f"sync: failed to read odds snapshot {latest} — {exc}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Could not read odds snapshot file.",
        )

    return JSONResponse({
        "snapshot_file": latest.name,
        "captured_at": datetime.fromtimestamp(
            latest.stat().st_mtime, tz=UTC
        ).isoformat(),
        "data": data,
    })


# ---------------------------------------------------------------------------
# GET /api/sync/latest-features
# ---------------------------------------------------------------------------

@router.get(
    "/latest-features",
    summary="Pull latest feature parquet as binary download",
    dependencies=[Depends(_require_sync_token)],
)
def get_latest_features() -> FileResponse:
    """
    Return the most recently built feature parquet file as a binary download.

    The predictor machine downloads this, writes it to its local storage, and
    uses it as input to model training / prediction.

    Response: application/octet-stream (parquet bytes).
    """
    features_dir = Path(settings.raw_snapshots_dir) / "features"
    files = sorted(
        features_dir.glob("features*.parquet"),
        key=lambda p: p.stat().st_mtime,
    ) if features_dir.exists() else []

    if not files:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No features parquet files found in {features_dir}.",
        )

    latest = files[-1]
    logger.info(
        f"sync: serving features file {latest.name} "
        f"({latest.stat().st_size / 1024:.1f} KB)"
    )

    return FileResponse(
        path=str(latest),
        media_type="application/octet-stream",
        filename=latest.name,
    )


# ---------------------------------------------------------------------------
# POST /api/sync/predictions
# ---------------------------------------------------------------------------

class PredictionRecord(BaseModel):
    match_id: int
    home_win_prob: float = Field(ge=0.0, le=1.0)
    away_win_prob: float = Field(ge=0.0, le=1.0)
    model_name: str
    generated_at: str | None = None  # ISO-8601 UTC


class SyncPredictionsPayload(BaseModel):
    predictions: list[PredictionRecord]
    predictor_run_id: str | None = None  # optional trace ID from predictor


@router.post(
    "/predictions",
    summary="Push model predictions from predictor → collector",
    status_code=status.HTTP_200_OK,
    dependencies=[Depends(_require_sync_token)],
)
def post_predictions(payload: SyncPredictionsPayload) -> dict:
    """
    Accept model predictions pushed by the predictor machine.

    Writes each prediction into the `predictions` table (or a staging parquet
    file if the DB table is unavailable). The collector's recommendation job
    then reads these predictions from DB when generating daily recommendations.

    Returns a summary of how many records were accepted / rejected.
    """
    if not payload.predictions:
        return {"accepted": 0, "rejected": 0, "message": "No predictions in payload."}

    accepted = 0
    rejected = 0
    errors: list[str] = []

    # Staging path: write to parquet so generate_recommendations can pick it up
    # even if the DB Prediction table schema isn't finalised yet.
    staging_dir = Path(settings.raw_snapshots_dir) / "sync_predictions"
    staging_dir.mkdir(parents=True, exist_ok=True)

    records = []
    for pred in payload.predictions:
        if abs(pred.home_win_prob + pred.away_win_prob - 1.0) > 0.01:
            rejected += 1
            errors.append(
                f"match_id={pred.match_id}: probs don't sum to 1 "
                f"({pred.home_win_prob:.4f} + {pred.away_win_prob:.4f})"
            )
            continue
        records.append({
            "match_id": pred.match_id,
            "home_win_prob": round(pred.home_win_prob, 6),
            "away_win_prob": round(pred.away_win_prob, 6),
            "model_name": pred.model_name,
            "generated_at": pred.generated_at or datetime.now(tz=UTC).isoformat(),
        })
        accepted += 1

    if records:
        ts = datetime.now(tz=UTC).strftime("%Y%m%dT%H%M%SZ")
        run_id = payload.predictor_run_id or "unknown"
        staging_path = staging_dir / f"predictions_{run_id}_{ts}.parquet"
        df = pd.DataFrame(records)
        df.to_parquet(staging_path, index=False)
        logger.info(
            f"sync: received {accepted} predictions from predictor "
            f"(run_id={run_id}) → {staging_path.name}"
        )

    if errors:
        logger.warning(f"sync: {rejected} prediction records rejected — {errors[:3]}")

    return {
        "accepted": accepted,
        "rejected": rejected,
        "message": (
            f"Stored {accepted} predictions."
            + (f" {rejected} rejected." if rejected else "")
        ),
    }


# ---------------------------------------------------------------------------
# GET /api/sync/status
# ---------------------------------------------------------------------------

@router.get(
    "/status",
    summary="Check sync endpoint availability and role",
    dependencies=[Depends(_require_sync_token)],
)
def get_sync_status() -> dict:
    """Health-check for the sync endpoints. Returns node role and data freshness."""
    features_dir = Path(settings.raw_snapshots_dir) / "features"
    odds_dir = Path(settings.raw_snapshots_dir) / "odds"

    feature_files = sorted(features_dir.glob("features*.parquet")) if features_dir.exists() else []
    odds_files = sorted(odds_dir.glob("odds*.json")) if odds_dir.exists() else []

    latest_features = feature_files[-1].name if feature_files else None
    latest_odds = odds_files[-1].name if odds_files else None

    return {
        "node_role": settings.node_role,
        "latest_features_file": latest_features,
        "latest_odds_file": latest_odds,
        "server_time": datetime.now(tz=UTC).isoformat(),
    }
