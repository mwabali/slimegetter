import json

from sqlalchemy import select

from app.application.strategy_validation import CostModel, validate_catalog
from app.infrastructure.mt5.gateway import MetaTrader5Gateway
from app.infrastructure.persistence.database import SessionLocal
from app.infrastructure.persistence.models import ExperimentRecord, StrategyRecord
from app.strategies.catalog import CATALOG


def run(count: int = 5000) -> tuple[int, int]:
    gateway = MetaTrader5Gateway.from_installed_package(allow_orders=False)
    gateway.connect()
    try:
        bars = gateway.get_recent_bars("XAUUSD", count)
        tick = gateway.get_tick("XAUUSD")
    finally:
        gateway.shutdown()
    observed_spread = tick.ask - tick.bid
    results = validate_catalog(CATALOG, bars, CostModel(spread=observed_spread, slippage="0.10"))
    with SessionLocal() as session:
        by_version = {row.version: row for row in session.scalars(select(StrategyRecord)).all()}
        previous = {row.name: row for row in session.scalars(select(ExperimentRecord).where(ExperimentRecord.name.like("catalog-validation:%"))).all()}
        for result in results:
            strategy = by_version[result.version]
            strategy.status = "SHADOW_CANDIDATE" if result.stable else "REJECTED"
            strategy.promotion_notes = "Passed cost-aware walk-forward validation; shadow only" if result.stable else "; ".join(result.rejection_reasons)
            name = f"catalog-validation:{result.version}"
            payload = result.model_dump(mode="json")
            experiment = previous.get(name)
            if experiment:
                experiment.status = "COMPLETED" if result.stable else "REJECTED"
                experiment.proposal_json = json.dumps(payload)
            else:
                session.add(ExperimentRecord(name=name, status="COMPLETED" if result.stable else "REJECTED", proposal_json=json.dumps(payload)))
        session.commit()
    return len(results), sum(result.stable for result in results)


if __name__ == "__main__":
    total, survivors = run()
    print(f"validated={total} shadow_candidates={survivors} rejected={total-survivors}")
