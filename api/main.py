"""
api/main.py
-----------
FastAPI application factory.
Mounts all route groups and configures middleware.
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api.routes import health, fixtures, predictions, recommendations, dashboard
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

    # CORS — restrict in production
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"] if settings.app_debug else [],
        allow_methods=["GET"],
        allow_headers=["*"],
    )

    # Route groups
    app.include_router(health.router, prefix="/health", tags=["health"])
    app.include_router(fixtures.router, prefix="/fixtures", tags=["fixtures"])
    app.include_router(predictions.router, prefix="/predictions", tags=["predictions"])
    app.include_router(recommendations.router, prefix="/recommendations", tags=["recommendations"])
    app.include_router(dashboard.router, prefix="/dashboard", tags=["dashboard"])

    return app


app = create_app()
