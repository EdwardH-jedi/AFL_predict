"""db/models/model_runs.py — Record of each model training run."""

from datetime import datetime

from sqlalchemy import DateTime, Float, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from db.base import Base


class ModelRun(Base):
    __tablename__ = "model_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    # Model identifier
    model_name: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    model_version: Mapped[str] = mapped_column(String(50), nullable=False)

    # Training data window
    train_from_season: Mapped[int | None] = mapped_column(Integer, nullable=True)
    train_to_season: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # Evaluation metrics on held-out validation set
    brier_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    log_loss: Mapped[float | None] = mapped_column(Float, nullable=True)
    accuracy: Mapped[float | None] = mapped_column(Float, nullable=True)

    # Path to serialised model artifact
    artifact_path: Mapped[str | None] = mapped_column(String(500), nullable=True)

    # Free-form metadata (JSON string)
    metadata_json: Mapped[str | None] = mapped_column(Text, nullable=True)

    # 'pending' | 'completed' | 'failed'
    # Identifies the training run that produced this model. Every model trained
    # in one invocation shares a batch id, which is what lets the recommendation
    # job require ensemble components to come from a single coherent batch
    # rather than assembling them independently by best score across history.
    # NULL on runs predating this column: those are not eligible for
    # batch-coherent assembly.
    training_batch_id: Mapped[str | None] = mapped_column(
        String(64), nullable=True, index=True
    )

    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    # Predictions produced by this run
    predictions: Mapped[list["Prediction"]] = relationship(  # type: ignore[name-defined]  # noqa: F821
        "Prediction", back_populates="model_run"
    )

    def __repr__(self) -> str:
        return f"<ModelRun id={self.id} model={self.model_name!r} status={self.status!r}>"
