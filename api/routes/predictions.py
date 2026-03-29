"""api/routes/predictions.py — Model prediction endpoints."""

from fastapi import APIRouter, Query
from pydantic import BaseModel

from api.dependencies import DbSession
from db.models.predictions import Prediction

router = APIRouter()


class PredictionOut(BaseModel):
    id: int
    match_id: int
    model_run_id: int
    home_win_prob: float
    away_win_prob: float
    home_edge: float | None
    away_edge: float | None


@router.get("/", response_model=list[PredictionOut], summary="List predictions")
def list_predictions(
    db: DbSession,
    match_id: int | None = Query(None),
    model_run_id: int | None = Query(None),
    limit: int = Query(50, le=200),
) -> list[PredictionOut]:
    """Return model predictions, optionally filtered by match or model run."""
    query = db.query(Prediction)
    if match_id is not None:
        query = query.filter(Prediction.match_id == match_id)
    if model_run_id is not None:
        query = query.filter(Prediction.model_run_id == model_run_id)
    rows = query.limit(limit).all()
    return [
        PredictionOut(
            id=p.id,
            match_id=p.match_id,
            model_run_id=p.model_run_id,
            home_win_prob=p.home_win_prob,
            away_win_prob=p.away_win_prob,
            home_edge=p.home_edge,
            away_edge=p.away_edge,
        )
        for p in rows
    ]
