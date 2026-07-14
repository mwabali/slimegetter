from datetime import UTC, datetime
from decimal import Decimal

from app.application.mt5_sync import Mt5ReadOnlySynchronizer
from app.infrastructure.mt5.gateway import Mt5Fill, Mt5Position
from app.infrastructure.persistence.models import Base, ClosedTradeRecord, PositionRecord
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session


def test_position_sync_replaces_stale_read_only_state() -> None:
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    position = Mt5Position("1", "XAUUSD", "BUY", Decimal("0.01"), Decimal("2300"), None, None, Decimal("1.2"), datetime.now(UTC))
    with Session(engine) as session:
        Mt5ReadOnlySynchronizer().sync_positions(session, (position,))
        assert session.scalar(select(PositionRecord).where(PositionRecord.ticket == "1")) is not None
        Mt5ReadOnlySynchronizer().sync_positions(session, ())
        assert session.scalar(select(PositionRecord).where(PositionRecord.ticket == "1")) is None


def test_exit_fill_is_promoted_to_closed_trade_once() -> None:
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    filled_at = datetime.now(UTC)
    fill = Mt5Fill("deal-1", "order-1", "XAUUSD", "SELL", Decimal("0.01"), Decimal("2301"), Decimal("4.5"), filled_at, "OUT")
    with Session(engine) as session:
        sync = Mt5ReadOnlySynchronizer()
        sync.sync_fills(session, (fill,))
        sync.sync_fills(session, (fill,))
        rows = session.scalars(select(ClosedTradeRecord)).all()
        assert len(rows) == 1
        assert rows[0].source_deal_ticket == "deal-1"
