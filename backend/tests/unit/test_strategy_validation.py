from datetime import UTC, datetime, timedelta
from decimal import Decimal

from app.application.strategy_validation import CostModel, evaluate_latest_signal, validate_catalog
from app.infrastructure.mt5.gateway import Mt5Bar
from app.strategies.catalog import CATALOG


def test_validation_is_deterministic_and_ranked() -> None:
    start = datetime(2026, 1, 1, tzinfo=UTC)
    bars = tuple(Mt5Bar(start + timedelta(minutes=5*i), Decimal(str(2300 + i*0.05)), Decimal(str(2301 + i*0.05)), Decimal(str(2299 + i*0.05)), Decimal(str(2300 + i*0.05))) for i in range(650))
    specs = (CATALOG[0], CATALOG[25])
    first = validate_catalog(specs, bars, CostModel(spread="0.3", slippage="0.1"))
    second = validate_catalog(specs, bars, CostModel(spread="0.3", slippage="0.1"))
    assert first == second
    assert {result.rank for result in first} == {1, 2}
    assert all(len(result.out_of_sample) == 2 for result in first)


def test_forward_signal_engine_supports_every_catalog_family() -> None:
    start = datetime(2026, 1, 1, tzinfo=UTC)
    bars = tuple(Mt5Bar(start + timedelta(minutes=5*i), Decimal(str(2300 + i*0.05)), Decimal(str(2301 + i*0.05)), Decimal(str(2299 + i*0.05)), Decimal(str(2300 + i*0.05))) for i in range(250))
    representative = {spec.family: spec for spec in CATALOG}
    assert len(representative) == 15
    for spec in representative.values():
        assert evaluate_latest_signal(spec, bars) in {"BUY", "SELL", "HOLD"}
