"""
api/main.py
-----------
FastAPI application factory.
Mounts all route groups and configures middleware.
"""

from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from api.routes import (
    dashboard,
    dashboard_ui,
    data_sync,
    discord_history,
    fixtures,
    health,
    predictions,
    recommendations,
    tab_tracking,
)
from config.settings import get_settings

settings = get_settings()


def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""
    app = FastAPI(
        title="AFL Predict API",
        description="Research API for AFL head-to-head betting analysis (paper trading only).",
        version="0.1.0",
        docs_url="/docs",
        redoc_url="/redoc",
    )

    # CORS — allow the dashboard frontend (Vite dev + configured prod URL).
    # POST is required by /api/tab/record-bet and /api/tab/settle-bet/{id}.
    allowed_origins = _resolve_cors_origins(settings)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=allowed_origins,
        allow_methods=["GET", "POST"],
        allow_headers=["*"],
        allow_credentials=False,
    )

    # Route groups
    app.include_router(health.router, prefix="/health", tags=["health"])
    app.include_router(fixtures.router, prefix="/fixtures", tags=["fixtures"])
    app.include_router(predictions.router, prefix="/predictions", tags=["predictions"])
    app.include_router(recommendations.router, prefix="/recommendations", tags=["recommendations"])
    app.include_router(dashboard.router, prefix="/dashboard", tags=["dashboard"])
    app.include_router(dashboard_ui.router, prefix="/api/dashboard", tags=["dashboard-ui"])
    app.include_router(data_sync.router, prefix="/api/sync", tags=["sync"])
    app.include_router(tab_tracking.router, prefix="/api/tab", tags=["tab"])
    app.include_router(discord_history.router, prefix="/discord", tags=["discord"])

    # Serve static files (dashboard.html etc.)
    static_dir = Path(__file__).parent.parent / "static"
    if static_dir.exists():
        app.mount("/static", StaticFiles(directory=static_dir), name="static")

    return app


def _resolve_cors_origins(cfg) -> list[str]:
    """Build the allowed origins list from settings.

    Always includes the configured frontend URL and the standard Vite dev origins.
    In debug mode we also accept the 127.0.0.1 equivalents to avoid localhost
    rewrites tripping the browser.
    """
    origins: list[str] = []
    if cfg.frontend_url:
        origins.append(cfg.frontend_url.rstrip("/"))
    # Vite dev defaults
    origins.extend([
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ])
    if cfg.app_debug:
        origins.extend([
            "http://localhost:3000",
            "http://127.0.0.1:3000",
        ])
    # De-duplicate while preserving order
    seen: set[str] = set()
    deduped: list[str] = []
    for o in origins:
        if o and o not in seen:
            seen.add(o)
            deduped.append(o)
    return deduped


app = create_app()
