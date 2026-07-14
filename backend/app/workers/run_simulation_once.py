"""Advance the persistent paper ledger without any MT5 order authority."""
import json
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import select

from app.application.simulation import bar_is_after_entry, evaluate_bar
from app.domain.journal.repository import TradeJournalRepository
from app.infrastructure.mt5.gateway import MetaTrader5Gateway
from app.infrastructure.persistence.database import SessionLocal
from app.infrastructure.persistence.models import DecisionEventRecord, SimulatedPositionRecord

WORKER_STARTED_AT = datetime.now(UTC)


def run_once() -> dict[str, int]:
    repository = TradeJournalRepository()
    gateway = MetaTrader5Gateway.from_installed_package(allow_orders=False)
    gateway.connect()
    try:
        latest_bar = gateway.get_recent_bars("XAUUSD", 30)[-1]
    finally:
        gateway.shutdown()

    opened = closed = 0
    with SessionLocal() as session:
        repository.record_heartbeat(session, "simulation-worker", "RUNNING", "Paper ledger cycle started")
        open_rows = tuple(session.scalars(select(SimulatedPositionRecord).where(SimulatedPositionRecord.status == "OPEN")).all())
        for row in open_rows:
            # Never use pre-entry price action from the candle containing the
            # entry. Start barrier evaluation with the following M5 candle.
            if not bar_is_after_entry(row.opened_at, latest_bar.time):
                continue
            result = evaluate_bar(
                row.side, Decimal(str(row.entry_price)), Decimal(str(row.stop_loss)), Decimal(str(row.take_profit)),
                Decimal(str(latest_bar.high)), Decimal(str(latest_bar.low)),
            )
            if result is None:
                continue
            row.status = "CLOSED"; row.exit_price = result.price
            row.pnl = result.pnl_per_unit * Decimal(str(row.volume))
            row.close_reason = result.reason; row.closed_at = datetime.now(UTC)
            session.commit()
            repository.append_event(session, row.correlation_id, "SIMULATION", "SIMULATED_TRADE_CLOSED", {
                "position_id": str(row.id), "exit_price": str(result.price),
                "pnl": str(row.pnl), "reason": result.reason, "execution_authority": False,
            })
            closed += 1

        approved = tuple(session.scalars(select(DecisionEventRecord).where(
            DecisionEventRecord.agent_name == "COMMANDER_ERWIN",
            DecisionEventRecord.event_type == "RISK_DECISION",
            DecisionEventRecord.created_at >= WORKER_STARTED_AT,
        ).order_by(DecisionEventRecord.created_at)).all())
        for decision_event in approved:
            decision = json.loads(decision_event.payload_json)
            if decision.get("status") != "APPROVED":
                continue
            exists = session.scalar(select(SimulatedPositionRecord).where(SimulatedPositionRecord.correlation_id == decision_event.correlation_id))
            if exists:
                journaled = session.scalar(select(DecisionEventRecord.id).where(
                    DecisionEventRecord.correlation_id == decision_event.correlation_id,
                    DecisionEventRecord.agent_name == "SIMULATION",
                    DecisionEventRecord.event_type == "SIMULATED_TRADE_OPENED",
                ))
                if not journaled:
                    repository.append_event(session, exists.correlation_id, "SIMULATION", "SIMULATED_TRADE_OPENED", {
                        "position_id": str(exists.id), "side": exists.side, "entry_price": str(exists.entry_price),
                        "stop_loss": str(exists.stop_loss), "take_profit": str(exists.take_profit),
                        "volume": str(exists.volume), "execution_authority": False, "reconciled": True,
                    })
                continue
            proposal_event = session.scalar(select(DecisionEventRecord).where(
                DecisionEventRecord.correlation_id == decision_event.correlation_id,
                DecisionEventRecord.agent_name == "EREN",
                DecisionEventRecord.event_type == "TRADE_PROPOSAL",
            ))
            if proposal_event is None:
                continue
            proposal = json.loads(proposal_event.payload_json)
            indicators = proposal.get("indicators_used") or ["eren-shadow"]
            row = SimulatedPositionRecord(
                correlation_id=decision_event.correlation_id,
                strategy_version=str(indicators[0])[:64], symbol="XAUUSD", side=proposal["side"],
                volume=Decimal(str(proposal["volume"])), entry_price=Decimal(str(proposal["entry_price"])),
                stop_loss=Decimal(str(proposal["stop_loss"])), take_profit=Decimal(str(proposal["take_profit"])),
            )
            session.add(row); session.commit()
            repository.append_event(session, row.correlation_id, "SIMULATION", "SIMULATED_TRADE_OPENED", {
                "position_id": str(row.id), "side": row.side, "entry_price": str(row.entry_price),
                "stop_loss": str(row.stop_loss), "take_profit": str(row.take_profit),
                "volume": str(row.volume), "execution_authority": False,
            })
            opened += 1
        repository.record_heartbeat(session, "simulation-worker", "HEALTHY", f"Paper ledger advanced: opened={opened}, closed={closed}")
    return {"opened": opened, "closed": closed}


if __name__ == "__main__":
    print(json.dumps(run_once()))
