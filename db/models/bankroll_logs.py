"""db/models/bankroll_logs.py — Hypothetical bankroll ledger for paper trading."""

from datetime import datetime

from sqlalchemy import DateTime, Float, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from db.base import Base


class BankrollLog(Base):
    __tablename__ = "bankroll_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    # Event type: 'deposit' | 'withdrawal' | 'bet_placed' | 'bet_settled'
    event_type: Mapped[str] = mapped_column(String(30), nullable=False)

    # Running balance after this event
    balance_after: Mapped[float] = mapped_column(Float, nullable=False)

    # Change amount (positive = credit, negative = debit)
    amount: Mapped[float] = mapped_column(Float, nullable=False)

    # Optional reference to a recommendation
    recommendation_id: Mapped[int | None] = mapped_column(Integer, nullable=True)

    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    def __repr__(self) -> str:
        return (
            f"<BankrollLog id={self.id} event={self.event_type!r} "
            f"amount={self.amount} balance_after={self.balance_after}>"
        )
