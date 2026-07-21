"""Read-only synchronization of MT5 account state into the audit database."""
from datetime import UTC, datetime

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.infrastructure.mt5.gateway import Mt5Fill, Mt5Position
from app.infrastructure.persistence.models import ClosedTradeRecord, FillRecord, PositionRecord


class Mt5ReadOnlySynchronizer:
    def sync_positions(self, session: Session, positions: tuple[Mt5Position, ...]) -> None:
        now = datetime.now(UTC)
        seen = {position.ticket for position in positions}
        if seen:
            session.execute(delete(PositionRecord).where(PositionRecord.ticket.not_in(seen)))
        else:
            session.execute(delete(PositionRecord))
        for position in positions:
            session.merge(
                PositionRecord(
                    ticket=position.ticket, symbol=position.symbol, side=position.side,
                    volume=position.volume, price_open=position.price_open, stop_loss=position.stop_loss,
                    take_profit=position.take_profit, profit=position.profit,
                    opened_at=position.opened_at, synced_at=now,
                )
            )
        session.commit()

    def sync_fills(self, session: Session, fills: tuple[Mt5Fill, ...]) -> None:
        for fill in fills:
            session.merge(
                FillRecord(
                    deal_ticket=fill.deal_ticket, order_ticket=fill.order_ticket,
                    symbol=fill.symbol, side=fill.side, volume=fill.volume, price=fill.price,
                    profit=fill.profit, filled_at=fill.filled_at, entry=fill.entry,
                    position_ticket=fill.position_ticket,
                    synced_at=datetime.now(UTC),
                )
            )
            if fill.entry in {"OUT", "OUT_BY"} and session.scalar(select(ClosedTradeRecord).where(ClosedTradeRecord.source_deal_ticket == fill.deal_ticket)) is None:
                session.add(ClosedTradeRecord(strategy_version="mt5-imported@1.0", session=self._session_name(fill.filled_at), pnl=fill.profit, reward_risk=0, source_deal_ticket=fill.deal_ticket, closed_at=fill.filled_at))
        session.commit()

    def latest_fill_time(self, session: Session) -> datetime | None:
        row = session.scalar(select(FillRecord).order_by(FillRecord.filled_at.desc()).limit(1))
        return row.filled_at if row else None

    @staticmethod
    def _session_name(timestamp: datetime) -> str:
        hour = timestamp.hour
        if 7 <= hour < 16:
            return "LONDON"
        if 13 <= hour < 22:
            return "NEW_YORK"
        if 22 <= hour or hour < 7:
            return "ASIA"
        return "OFF_HOURS"
