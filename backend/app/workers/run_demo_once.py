"""Run one fully guarded MT5 demo cycle.

This module refuses live accounts and requires three independent configuration
gates. It must only be launched after shadow and simulation verification.
"""
import json
from datetime import UTC, datetime
from decimal import ROUND_DOWN, Decimal
from sqlalchemy import select

from app.agents.erwin.service import CommanderErwinService
from app.application.execution import DemoExecutionService
from app.application.position_sizing import PositionSizer
from app.application.workflows.decision_preview import DecisionPreview
from app.config.settings import get_settings
from app.domain.journal.repository import TradeJournalRepository
from app.domain.trading.models import ProposalStatus, RiskProfile, SymbolSpecification
from app.infrastructure.market_data.factory import build_economic_calendar_provider
from app.infrastructure.mt5.gateway import MetaTrader5Gateway
from app.infrastructure.persistence.database import SessionLocal
from app.infrastructure.persistence.models import ExecutionAttemptRecord
from app.workers.shadow_mode import ShadowModeRunner
from app.workers.run_shadow_once import _collective_events


def _profile(settings) -> RiskProfile:
    return RiskProfile(
        risk_per_trade_pct=str(settings.max_risk_per_trade_pct),
        max_daily_loss_pct=str(settings.max_daily_loss_pct),
        max_weekly_loss_pct=str(settings.max_weekly_loss_pct),
        max_spread=str(settings.max_spread),
        max_exposure_pct=str(settings.max_exposure_pct),
        max_simultaneous_trades=settings.max_simultaneous_trades,
        min_reward_risk=str(settings.minimum_reward_risk),
    )


def run_once() -> str:
    settings = get_settings()
    if settings.trading_mode != "demo":
        raise RuntimeError("Demo worker refuses non-demo trading mode")
    if not settings.execution_enabled or not settings.demo_trading_confirmed:
        raise RuntimeError("Demo execution requires XAU_EXECUTION_ENABLED and XAU_DEMO_TRADING_CONFIRMED")
    if settings.kill_switch_active:
        raise RuntimeError("Demo execution blocked by XAU_KILL_SWITCH_ACTIVE")

    repository = TradeJournalRepository()
    with SessionLocal() as session:
        repository.record_heartbeat(session, "demo-worker", "RUNNING", "Guarded demo cycle started")
    profile = _profile(settings)
    observation_active = bool(settings.observation_mode_until and datetime.now(UTC) < settings.observation_mode_until)
    gateway = MetaTrader5Gateway.from_installed_package(
        allow_orders=True,
        kill_switch=lambda: get_settings().kill_switch_active,
    )
    preview = ShadowModeRunner().run_once(
        gateway,
        profile,
        build_economic_calendar_provider(settings),
        settings.max_tick_age_seconds,
        settings.max_bar_age_seconds,
        settings.mt5_server_utc_offset_hours,
        Decimal(str(settings.observation_min_market_quality)) if observation_active else Decimal("7.00"),
        observation_active,
    )

    if preview.eren is None or preview.erwin is None or preview.erwin.status is not ProposalStatus.APPROVED:
        with SessionLocal() as session:
            repository.record_preview(session, preview)
            repository.record_collective_events(session, preview.correlation_id, ((6, "EXECUTION", "NO_ORDER", json.dumps({"reason": preview.final_message})),))
            collective = _collective_events(session, preview.correlation_id, preview.final_message, 7)
            session.rollback()
            repository.record_collective_events(session, preview.correlation_id, collective)
            repository.record_heartbeat(session, "demo-worker", "HEALTHY", "Demo cycle completed with no order")
        return "NO_ORDER"

    gateway.connect()
    try:
        account = gateway.get_account_snapshot()
        raw = gateway.get_symbol_specification("XAUUSD")
        specification = SymbolSpecification(
            point=Decimal(str(raw.point)),
            volume_min=Decimal(str(raw.volume_min)),
            volume_max=Decimal(str(raw.volume_max)),
            volume_step=Decimal(str(raw.volume_step)),
            trade_contract_size=Decimal(str(raw.trade_contract_size)),
        )
        sized = PositionSizer().size(preview.eren, account.equity, specification)
        proposal = preview.eren.model_copy(update={"volume": sized.volume})
        tick = gateway.get_tick("XAUUSD")
        decision = CommanderErwinService().evaluate(proposal, account, profile, tick.ask - tick.bid)
        if decision.status is ProposalStatus.APPROVED and decision.recommended_size_multiplier < Decimal("1"):
            raw_volume = proposal.volume * decision.recommended_size_multiplier
            adjusted_volume = (raw_volume / specification.volume_step).to_integral_value(rounding=ROUND_DOWN) * specification.volume_step
            if adjusted_volume < specification.volume_min:
                decision = decision.model_copy(update={
                    "status": ProposalStatus.REJECTED,
                    "risk_posture": "TECHNICAL_STOP",
                    "reasons": ("Broker minimum lot cannot express the authorized reduced risk", *decision.reasons),
                })
            else:
                proposal = proposal.model_copy(update={
                    "volume": adjusted_volume,
                    "expected_risk_pct": proposal.expected_risk_pct * decision.recommended_size_multiplier,
                    "reasons": (*proposal.reasons, f"Erwin committed {decision.recommended_size_multiplier * 100}% calculated-risk size"),
                })
        safe_preview = preview.model_copy(update={
            "eren": proposal,
            "erwin": decision,
            "final_message": f"{decision.status.value}: {decision.reasons[0]}",
        })
        with SessionLocal() as session:
            repository.record_preview(session, safe_preview)
        if decision.status is not ProposalStatus.APPROVED:
            with SessionLocal() as session:
                repository.record_collective_events(session, proposal.correlation_id, ((6, "EXECUTION", "NO_ORDER", json.dumps({"reason": decision.reasons})),))
                collective = _collective_events(session, proposal.correlation_id, safe_preview.final_message, 7)
                session.rollback()
                repository.record_collective_events(session, proposal.correlation_id, collective)
                repository.record_heartbeat(session, "demo-worker", "HEALTHY", "Erwin rejected the resized proposal; no order")
            return "NO_ORDER"
        with SessionLocal() as session:
            existing_attempt = session.scalar(select(ExecutionAttemptRecord).where(ExecutionAttemptRecord.proposal_id == proposal.id))
            if existing_attempt is not None:
                repository.append_event(session, proposal.correlation_id, "EXECUTION", "DUPLICATE_SUBMISSION_BLOCKED", {
                    "proposal_id": str(proposal.id), "attempt_status": existing_attempt.status,
                    "broker_ticket": existing_attempt.broker_ticket, "execution_authority": False,
                })
                repository.record_heartbeat(session, "demo-worker", "ERROR", "Duplicate demo submission blocked; reconciliation required")
                return "NO_ORDER_DUPLICATE_BLOCKED"
            session.add(ExecutionAttemptRecord(proposal_id=proposal.id, correlation_id=proposal.correlation_id, status="CLAIMED"))
            session.commit()
        try:
            ticket = DemoExecutionService(gateway, True, "demo").submit(proposal, decision)
        except Exception as exc:
            with SessionLocal() as session:
                attempt = session.scalar(select(ExecutionAttemptRecord).where(ExecutionAttemptRecord.proposal_id == proposal.id))
                if attempt:
                    attempt.status = "UNKNOWN_RECONCILE"; attempt.error_type = type(exc).__name__; session.commit()
                repository.append_event(session, proposal.correlation_id, "EXECUTION", "DEMO_ORDER_STATUS_UNKNOWN", {
                    "proposal_id": str(proposal.id), "error_type": type(exc).__name__,
                    "message": "Automatic retry blocked pending broker reconciliation",
                })
                repository.record_heartbeat(session, "demo-worker", "ERROR", "Demo order outcome unknown; reconciliation required")
            raise
        with SessionLocal() as session:
            attempt = session.scalar(select(ExecutionAttemptRecord).where(ExecutionAttemptRecord.proposal_id == proposal.id))
            if attempt:
                attempt.status = "SUBMITTED"; attempt.broker_ticket = ticket; session.commit()
        with SessionLocal() as session:
            repository.record_collective_events(session, proposal.correlation_id, ((6, "EXECUTION", "DEMO_ORDER_SUBMITTED", json.dumps({"ticket": ticket, "volume": str(sized.volume), "risk_amount": str(sized.risk_amount)})),))
            collective = _collective_events(session, proposal.correlation_id, safe_preview.final_message, 7)
            session.rollback()
            repository.record_collective_events(session, proposal.correlation_id, collective)
            repository.record_heartbeat(session, "demo-worker", "HEALTHY", f"Demo order submitted: {ticket}")
        return ticket
    finally:
        gateway.shutdown()


if __name__ == "__main__":
    print(run_once())
