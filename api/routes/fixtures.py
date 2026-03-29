"""api/routes/fixtures.py — Upcoming and past match fixture endpoints."""

from fastapi import APIRouter, Query
from pydantic import BaseModel

from api.dependencies import DbSession
from db.models.matches import Match

router = APIRouter()


class FixtureOut(BaseModel):
    id: int
    season: int
    round_number: int
    round_label: str | None
    home_team_id: int
    away_team_id: int
    venue: str | None
    match_time: str | None
    result: str | None

    class Config:
        from_attributes = True


@router.get("/", response_model=list[FixtureOut], summary="List fixtures")
def list_fixtures(
    db: DbSession,
    season: int | None = Query(None, description="Filter by season year"),
    limit: int = Query(50, le=200),
) -> list[FixtureOut]:
    """
    Return a list of AFL fixtures.
    Optionally filter by season. Ordered by match_time ascending.
    """
    query = db.query(Match).order_by(Match.match_time)
    if season is not None:
        query = query.filter(Match.season == season)
    matches = query.limit(limit).all()
    return [
        FixtureOut(
            id=m.id,
            season=m.season,
            round_number=m.round_number,
            round_label=m.round_label,
            home_team_id=m.home_team_id,
            away_team_id=m.away_team_id,
            venue=m.venue,
            match_time=m.match_time.isoformat() if m.match_time else None,
            result=m.result,
        )
        for m in matches
    ]
