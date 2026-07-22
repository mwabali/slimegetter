from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.application.defensive_risk import (
    DefensiveRiskEngine,
    DefensiveVolumeBlocked,
    RiskSizingMode,
    RiskState,
    calculate_allowed_volume,
)
from app.config.settings import Settings
from app.domain.trading.models import AccountSnapshot, SymbolSpecification
from app.infrastructure.persistence.models import Base, ClosedTradeRecord


def account() -> AccountSnapshot:
    return AccountSnapshot(
        account_id="demo",
        balance="10000",
        equity="10000",
        free_margin="9000",
        open_position_count=0,
        current_exposure_pct="0",
        realized_daily_pnl="0",
        realized_weekly_pnl="0",
    )


def settings(**overrides: object) -> Settings:
    values = {"environment": "test", "risk_auto_reset_session_boundary": False}
    values.update(overrides)
    return Settings(**values)


def specification() -> SymbolSpecification:
    return SymbolSpecification(
        symbol="XAUUSD.vx",
        point="0.01",
        volume_min="0.01",
        volume_max="100",
        volume_step="0.01",
        volume_limit="50",
        trade_contract_size="100",
    )


def trade(pnl: str, closed_at: datetime, exit_reason: str | None = None) -> ClosedTradeRecord:
    return ClosedTradeRecord(
        id=uuid4(),
        strategy_version="test@1",
        session="LONDON",
        pnl=Decimal(pnl),
        reward_risk=Decimal("1.5"),
        exit_reason=exit_reason,
        closed_at=closed_at,
    )


def engine_session():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    return engine


def refreshed_state(session: Session, now: datetime, **config: object):
    return DefensiveRiskEngine().refresh(session, account(), now=now, settings=settings(**config))


def test_normal_caution_and_defensive_volume_are_downward_only() -> None:
    assessment = RiskStateAssessmentForTest(RiskState.NORMAL, "1")
    assert calculate_allowed_volume(Decimal("0.04"), Decimal("0.04"), assessment, specification(), RiskSizingMode.DEMO_ACTIVE).approved_volume == Decimal("0.04")
    caution = RiskStateAssessmentForTest(RiskState.CAUTION, "0.75")
    assert calculate_allowed_volume(Decimal("0.04"), Decimal("0.04"), caution, specification(), RiskSizingMode.DEMO_ACTIVE).approved_volume == Decimal("0.03")
    defensive = RiskStateAssessmentForTest(RiskState.DEFENSIVE, "0.50")
    assert calculate_allowed_volume(Decimal("0.04"), Decimal("0.04"), defensive, specification(), RiskSizingMode.DEMO_ACTIVE).approved_volume == Decimal("0.02")


def test_halted_blocks_new_volume() -> None:
    with pytest.raises(DefensiveVolumeBlocked, match="blocked"):
        calculate_allowed_volume(Decimal("0.04"), Decimal("0.04"), RiskStateAssessmentForTest(RiskState.HALTED, "0"), specification(), RiskSizingMode.DEMO_ACTIVE)


def test_demo_cooldown_override_allows_defensive_volume_without_bypassing_halt() -> None:
    assessment = RiskStateAssessmentForTest(RiskState.DEFENSIVE, "0.50", blocked=True)
    with pytest.raises(DefensiveVolumeBlocked):
        calculate_allowed_volume(Decimal("0.04"), Decimal("0.04"), assessment, specification(), RiskSizingMode.DEMO_ACTIVE)
    result = calculate_allowed_volume(
        Decimal("0.04"),
        Decimal("0.04"),
        assessment,
        specification(),
        RiskSizingMode.DEMO_ACTIVE,
        allow_cooldown_override=True,
    )
    assert result.approved_volume == Decimal("0.02")


def test_below_minimum_is_skipped_and_not_rounded_up() -> None:
    with pytest.raises(DefensiveVolumeBlocked, match="BELOW_BROKER_MINIMUM"):
        calculate_allowed_volume(Decimal("0.01"), Decimal("0.01"), RiskStateAssessmentForTest(RiskState.DEFENSIVE, "0.50"), specification(), RiskSizingMode.DEMO_ACTIVE)


def test_volume_step_is_normalized_downward() -> None:
    result = calculate_allowed_volume(Decimal("0.05"), Decimal("0.0375"), RiskStateAssessmentForTest(RiskState.NORMAL, "1"), specification(), RiskSizingMode.DEMO_ACTIVE)
    assert result.approved_volume == Decimal("0.03")


def test_losses_progress_to_caution_defensive_and_halted() -> None:
    engine = engine_session()
    now = datetime(2026, 7, 22, tzinfo=UTC)
    with Session(engine) as session:
        state = refreshed_state(session, now)
        session.commit()
        for index, pnl in enumerate(("-1", "-1"), 1):
            session.add(trade(pnl, now + timedelta(seconds=index)))
        session.commit()
        assert refreshed_state(session, now + timedelta(minutes=1)).state is RiskState.CAUTION
        session.add(trade("-1", now + timedelta(seconds=3)))
        session.commit()
        assert refreshed_state(session, now + timedelta(minutes=2)).state is RiskState.DEFENSIVE
        session.add(trade("-1", now + timedelta(seconds=4)))
        session.commit()
        assert refreshed_state(session, now + timedelta(minutes=3)).state is RiskState.HALTED
    engine.dispose()


def test_hard_stop_escalates_even_with_one_loss() -> None:
    engine = engine_session()
    now = datetime(2026, 7, 22, tzinfo=UTC)
    with Session(engine) as session:
        refreshed_state(session, now)
        session.commit()
        session.add(trade("-1", now + timedelta(seconds=1), "LEARNING_STOP_LIMIT"))
        session.commit()
        result = refreshed_state(session, now + timedelta(minutes=1))
        assert result.state is RiskState.CAUTION
        assert result.hard_stop_count == 1
        assert result.consecutive_hard_stops == 1
    engine.dispose()


def test_critical_incident_forces_halt() -> None:
    engine = engine_session()
    now = datetime(2026, 7, 22, tzinfo=UTC)
    with Session(engine) as session:
        result = refreshed_state(session, now, risk_auto_reset_session_boundary=False)
        result = DefensiveRiskEngine().refresh(session, account(), execution_locked=True, now=now + timedelta(seconds=1), settings=settings(risk_auto_reset_session_boundary=False))
        assert result.state is RiskState.HALTED
    engine.dispose()


def test_state_persists_across_restart_and_recovery_is_gradual() -> None:
    engine = engine_session()
    now = datetime(2026, 7, 22, tzinfo=UTC)
    with Session(engine) as session:
        refreshed_state(session, now)
        session.commit()
        session.add(trade("-1", now + timedelta(seconds=1)))
        session.add(trade("-1", now + timedelta(seconds=2)))
        session.add(trade("-1", now + timedelta(seconds=3)))
        session.commit()
        first = refreshed_state(session, now + timedelta(minutes=1))
        session.commit()
        assert first.state is RiskState.DEFENSIVE
    with Session(engine) as session:
        persisted = DefensiveRiskEngine.read(session)
        assert persisted is not None
        assert persisted.state is RiskState.DEFENSIVE
        for index in range(4, 7):
            session.add(trade("1.00", now + timedelta(seconds=index)))
        session.commit()
        recovered = refreshed_state(session, now + timedelta(minutes=2))
        assert recovered.state is RiskState.CAUTION
        session.add(trade("1.00", now + timedelta(seconds=7)))
        session.add(trade("1.00", now + timedelta(seconds=8)))
        session.add(trade("1.00", now + timedelta(seconds=9)))
        session.commit()
        assert refreshed_state(session, now + timedelta(minutes=3)).state is RiskState.NORMAL
    engine.dispose()


def test_shadow_keeps_actual_volume_but_records_smaller_recommendation() -> None:
    result = calculate_allowed_volume(Decimal("0.04"), Decimal("0.04"), RiskStateAssessmentForTest(RiskState.DEFENSIVE, "0.50"), specification(), RiskSizingMode.SHADOW)
    assert result.approved_volume == Decimal("0.04")
    assert result.adaptive_recommended_volume == Decimal("0.02")


def test_volume_above_configured_normal_ceiling_is_rejected() -> None:
    with pytest.raises(DefensiveVolumeBlocked, match="exceeds configured normal ceiling"):
        calculate_allowed_volume(Decimal("0.04"), Decimal("0.05"), RiskStateAssessmentForTest(RiskState.NORMAL, "1"), specification(), RiskSizingMode.DEMO_ACTIVE)


class RiskStateAssessmentForTest:
    def __init__(self, state: RiskState, multiplier: str, blocked: bool = False) -> None:
        self.state = state
        self.risk_multiplier = Decimal(multiplier)
        self.state_reason = "test"
        self.cooldown_until = datetime.now(UTC) + timedelta(minutes=5) if blocked else None
        self.blocked = blocked

    @property
    def new_entries_blocked(self) -> bool:
        return self.blocked or self.state in {RiskState.HALTED, RiskState.UNKNOWN}
