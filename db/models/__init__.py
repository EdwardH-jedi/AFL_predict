# Import all models here so SQLAlchemy registers them against Base.metadata.
# Order matters: DailyPipelineRun must precede PipelineRun (FK dependency).
from db.models.bankroll_logs import BankrollLog
from db.models.bet_outcomes import BetOutcome
from db.models.daily_pipeline_runs import DailyPipelineRun
from db.models.match_features import MatchFeature
from db.models.matches import Match
from db.models.model_runs import ModelRun
from db.models.odds_snapshots import OddsSnapshot
from db.models.pipeline_runs import PipelineRun
from db.models.predictions import Prediction
from db.models.recommendations import Recommendation
from db.models.teams import Team

__all__ = [
    "DailyPipelineRun",
    "Team",
    "Match",
    "MatchFeature",
    "OddsSnapshot",
    "ModelRun",
    "Prediction",
    "Recommendation",
    "BetOutcome",
    "BankrollLog",
    "PipelineRun",
]
