"""Record forward-only observations for validated strategy candidates."""
import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from sqlalchemy import select

from app.application.strategy_validation import evaluate_latest_signal
from app.domain.journal.repository import TradeJournalRepository
from app.infrastructure.mt5.gateway import MetaTrader5Gateway
from app.infrastructure.persistence.database import SessionLocal
from app.infrastructure.persistence.models import ExperimentRecord, StrategyRecord
from app.strategies.catalog import CATALOG
from app.strategies.coverage import build_coverage_plan


def run_once() -> int:
    by_version = {spec.version: spec for spec in CATALOG}
    gateway = MetaTrader5Gateway.from_installed_package(allow_orders=False)
    gateway.connect()
    try:
        bars = gateway.get_recent_bars("XAUUSD", 150)
        tick = gateway.get_tick("XAUUSD")
    finally:
        gateway.shutdown()
    observed = 0; now = datetime.now(UTC)
    plan = build_coverage_plan(CATALOG)
    situation_by_version = {
        version: bucket.situation
        for bucket in plan.situations
        for version in bucket.versions
    }
    reserve_versions = set(plan.reserve_versions)
    cohort_versions = tuple(dict.fromkeys((*plan.planned_versions, *plan.reserve_versions)))
    with SessionLocal() as session:
        pending = session.scalars(select(ExperimentRecord).where(ExperimentRecord.name.like("shadow-observation:%"), ExperimentRecord.status == "RUNNING")).all()
        for experiment in pending:
            payload = json.loads(experiment.proposal_json)
            observed_at = datetime.fromisoformat(payload["observed_at"])
            if now - observed_at < timedelta(hours=2):
                continue
            signal = payload["signal"]
            entry = (Decimal(payload["bid"]) + Decimal(payload["ask"])) / Decimal("2")
            exit_price = bars[-1].close
            direction = Decimal("1") if signal == "BUY" else Decimal("-1") if signal == "SELL" else Decimal("0")
            round_trip_cost = Decimal(payload["ask"]) - Decimal(payload["bid"]) + Decimal("0.20")
            payload["outcome_at"] = now.isoformat()
            payload["outcome_price"] = str(exit_price)
            payload["outcome_pnl"] = str((exit_price - entry) * direction - round_trip_cost if direction else Decimal("0"))
            payload["horizon_minutes"] = 120
            experiment.proposal_json = json.dumps(payload)
            experiment.status = "COMPLETED"
        rows = session.scalars(
            select(StrategyRecord).where(
                StrategyRecord.version.in_(cohort_versions),
                StrategyRecord.status.not_in(("REJECTED", "RETIRED")),
            )
        ).all()
        for row in rows:
            spec = by_version[row.version]
            row.status = "SHADOW"
            session.add(ExperimentRecord(
                name=f"shadow-observation:{row.version}:{now.isoformat()}",
                status="RUNNING",
                proposal_json=json.dumps({
                    "strategy_version": row.version,
                    "pool": "RESERVE" if row.version in reserve_versions else "CORE",
                    "situation": situation_by_version.get(row.version, "RESERVE"),
                    "observed_at": now.isoformat(),
                    "bar_time": bars[-1].time.isoformat(),
                    "bid": str(tick.bid), "ask": str(tick.ask),
                    "signal": evaluate_latest_signal(spec, bars),
                    "execution_authority": False,
                }),
            ))
            observed += 1
        session.commit()
        TradeJournalRepository().record_heartbeat(session, "strategy-shadow-worker", "HEALTHY", f"Recorded {observed} research-only strategy observations")
    return observed


if __name__ == "__main__":
    print(f"observed={run_once()}")
