"""api/routes/recommendations.py — Betting recommendation endpoints (paper trade only)."""

from fastapi import APIRouter, Query
from pydantic import BaseModel

from api.dependencies import DbSession
from db.models.recommendations import Recommendation

router = APIRouter()


class RecommendationOut(BaseModel):
    id: int
    prediction_id: int
    side: str
    recommended_odds: float
    stake_fraction: float
    stake_dollars: float | None
    paper_trade: bool
    status: str


@router.get("/", response_model=list[RecommendationOut], summary="List recommendations")
def list_recommendations(
    db: DbSession,
    status: str | None = Query(None, description="Filter by status: pending | settled | void"),
    limit: int = Query(50, le=200),
) -> list[RecommendationOut]:
    """
    Return betting recommendations. All are paper_trade=True in MVP.
    """
    query = db.query(Recommendation)
    if status is not None:
        query = query.filter(Recommendation.status == status)
    rows = query.limit(limit).all()
    return [
        RecommendationOut(
            id=r.id,
            prediction_id=r.prediction_id,
            side=r.side,
            recommended_odds=r.recommended_odds,
            stake_fraction=r.stake_fraction,
            stake_dollars=r.stake_dollars,
            paper_trade=r.paper_trade,
            status=r.status,
        )
        for r in rows
    ]
