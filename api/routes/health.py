"""api/routes/health.py — Health check endpoints."""

from datetime import datetime, timezone

from fastapi import APIRouter
from pydantic import BaseModel
from sqlalchemy import text

from api.dependencies import DbSession
from config.settings import get_settings

router = APIRouter()
settings = get_settings()


class HealthResponse(BaseModel):
    status: str
    app_env: str
    timestamp: datetime
    db_ok: bool
    paper_trade_only: bool


@router.get("/", response_model=HealthResponse, summary="System health check")
def health_check(db: DbSession) -> HealthResponse:
    """
    Returns overall system health.
    Checks database connectivity and reports configuration state.
    """
    db_ok = False
    try:
        db.execute(text("SELECT 1"))
        db_ok = True
    except Exception:
        pass

    return HealthResponse(
        status="ok" if db_ok else "degraded",
        app_env=settings.app_env,
        timestamp=datetime.now(tz=timezone.utc),
        db_ok=db_ok,
        paper_trade_only=settings.paper_trade_only,
    )
