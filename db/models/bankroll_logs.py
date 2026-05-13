"""db/models/bankroll_logs.py — Bankroll ledger for paper trading and live TAB bets."""

from datetime import datetime

from sqlalchemy import DateTime, Float, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from db.base import Base


class BankrollLog(Base):
    __tablename__ = "bankroll_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    # 'paper'  — simulated bankroll (starts at $1000, no real money)
    # 'live'   — actual AUD bankroll from TAB bets
    log_type: Mapped[str] = mapped_column(
        String(10), nullable=False, default="paper", server_default="paper"
    )

    # Event type: 'deposit' | 'withdrawal' | 'bet_placed' | 'bet_settled'
    event_type: Mapped[str] = mapped_column(String(30), nullable=False)

    # Running balance after this event (AUD for live, virtual units for paper)
    balance_after: Mapped[float] = mapped_column(Float, nullable=False)

    # Change amount (positive = credit, negative = debit)
    amount: Mapped[float] = mapped_column(Float, nullable=False)

    # Optional reference (recommendation_id for paper, bet_outcome_id for live)
    recommendation_id: Mapped[int | None] = mapped_column(Integer, nullable=True)

    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    def __repr__(self) -> str:
        return (
            f"<BankrollLog id={self.id} type={self.log_type!r} "
            f"event={self.event_type!r} amount={self.amount} balance_after={self.balance_after}>"
        )
