"""
config/settings.py
------------------
Centralised application settings loaded from environment variables / .env file.
Uses pydantic-settings for type-safe config with validation.
"""

from functools import lru_cache
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """All application settings. Values are read from environment / .env file."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # --- Application ---
    app_env: Literal["development", "staging", "production"] = "development"
    app_debug: bool = True
    log_level: str = "INFO"

    # --- Database ---
    db_url: str = Field(
        default="sqlite:///./afl_predict.db",
        description="SQLAlchemy database URL. Use SQLite for local dev.",
    )

    # --- API ---
    api_host: str = "0.0.0.0"
    api_port: int = 8000
    api_secret_key: str = "changeme-use-a-long-random-string"

    # --- Frontend ---
    # Origin of the React dashboard. Added to the CORS allow-list in addition
    # to the Vite dev defaults (http://localhost:5173, http://127.0.0.1:5173).
    # Example prod: "http://rx6600.local:5173" or the RX 6600 static host.
    frontend_url: str = Field(
        default="",
        description="Primary frontend origin for CORS. Empty = dev-only (Vite defaults used).",
    )

    # --- AFL Data Source: Squiggle API (squiggle.com.au) ---
    # Public, free, no API key. Must set a descriptive User-Agent per their usage policy.
    squiggle_base_url: str = "https://api.squiggle.com.au"
    squiggle_user_agent: str = "AFL-predict-research/0.1 (personal research; non-commercial)"

    # --- Odds Source: The Odds API (the-odds-api.com) ---
    # Free tier: 500 requests/month. Covers AU region bookmakers (TAB, Sportsbet, etc.)
    # Register at https://the-odds-api.com to get a free key.
    # TODO: Confirm TAB is available in your subscription tier before relying on it.
    odds_api_base_url: str = "https://api.the-odds-api.com"
    odds_api_key: str = ""  # Required for live use; leave blank to skip odds ingestion
    # Comma-separated bookmaker preference order (first available wins)
    odds_bookmaker_preference: str = "tab,unibet,sportsbet,betfair_ex_au"
    # AU odds region covers Australian bookmakers
    odds_api_region: str = "au"

    # --- Storage ---
    raw_snapshots_dir: str = "./storage/raw_snapshots"
    model_artifacts_dir: str = "./storage/model_artifacts"

    # --- Pipeline ---
    paper_trade_only: bool = True
    min_edge_threshold: float = Field(
        default=0.03,
        description="Minimum implied edge (model prob - implied prob) to generate recommendation.",
    )
    max_kelly_fraction: float = Field(
        default=0.05,
        description="Hard cap on Kelly fraction. Conservative — never exceed 5%.",
    )

    # --- Pipeline Retry ---
    # Retry only applies to ingestion jobs (network I/O).
    pipeline_max_retries: int = Field(
        default=2,
        description="Max retry attempts for retryable jobs before marking failed.",
    )
    pipeline_retry_delay_seconds: float = Field(
        default=30.0,
        description="Seconds to wait between retries.",
    )

    # --- Data Freshness ---
    # Odds are considered stale if the newest snapshot is older than this.
    odds_freshness_hours: float = Field(
        default=26.0,
        description="Hours before odds snapshots are considered stale.",
    )
    # AFL fixtures are considered stale after this many hours.
    afl_freshness_hours: float = Field(
        default=48.0,
        description="Hours before AFL fixture data is considered stale.",
    )

    # --- Daily Summary ---
    daily_summary_dir: str = "./storage/daily_summaries"

    # --- Live-Readiness Thresholds ---
    # System will not suggest live trial unless all these are met.
    readiness_min_settled_bets: int = Field(
        default=100,
        description="Minimum settled paper bets before readiness can be confirmed.",
    )
    readiness_max_drawdown: float = Field(
        default=0.25,
        description="Maximum acceptable bankroll drawdown fraction (0.25 = 25%).",
    )
    readiness_max_ece: float = Field(
        default=0.06,
        description="Maximum acceptable Expected Calibration Error.",
    )
    readiness_max_failed_jobs_7d: int = Field(
        default=2,
        description="Max hard-dep job failures allowed in last 7 days before readiness is blocked.",
    )

    # --- Ensemble Weights ---
    ensemble_weight_bookmaker: float = Field(default=0.30)
    ensemble_weight_elo: float = Field(default=0.10)
    ensemble_weight_xgboost: float = Field(default=0.35)
    ensemble_weight_poisson: float = Field(default=0.25)

    # --- Dual-Machine Architecture ---
    # NODE_ROLE controls which pipeline jobs run on this machine:
    #   'standalone'  — runs all jobs (single-machine default)
    #   'collector'   — RX 6600: ingestion only (ingest_afl, ingest_tab_odds + freshness)
    #   'predictor'   — RTX 5080: modelling only (build_features, recommendations, settle)
    node_role: Literal["standalone", "collector", "predictor"] = Field(
        default="standalone",
        description="Role of this machine in the dual-machine deployment.",
    )
    predictor_api_url: str = Field(
        default="",
        description="Base URL of the collector's API, e.g. http://rx6600:8000 (predictor only).",
    )

    # --- Live Bankroll ---
    live_initial_bankroll: float = Field(default=1000.0)

    # --- TAB Bookmaker Confirmation ---
    # Set to true in .env once you have confirmed that TAB is available in your
    # Odds API subscription tier (check https://the-odds-api.com/liveapi/guides/v4/#parameters
    # for the list of bookmakers returned by your key).
    tab_bookmaker_confirmed: bool = Field(
        default=False,
        description="Set true once you have verified TAB appears in your Odds API responses.",
    )

    # --- Discord Notifications ---
    # Set DISCORD_WEBHOOK_URL in .env to enable alerts.
    # Create a webhook: Discord 채널 설정 → 연동 → 웹후크 → 새 웹후크 → URL 복사
    discord_webhook_url: str = Field(default="", description="Discord webhook URL for alerts")
    discord_enabled: bool = Field(
        default=False,
        description="Master switch for Discord notifications. Set to true in .env once configured.",
    )
    # --- Discord Bot (read-back) ---
    # Required for reading message history from the channel.
    # Create a bot at https://discord.com/developers/applications, enable
    # MESSAGE CONTENT INTENT, add to server with Read Message History permission.
    discord_bot_token: str = Field(
        default="",
        description="Discord bot token for reading message history",
    )
    discord_channel_id: str = Field(
        default="",
        description="Discord channel ID to read bet notifications from",
    )

    @property
    def APP_ENV(self) -> str:
        """Uppercase alias for app_env (convenience accessor)."""
        return self.app_env.upper()


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return cached Settings instance. Call this everywhere instead of instantiating directly."""
    return Settings()


# Module-level singleton — use get_settings() in new code for testability.
settings = get_settings()
