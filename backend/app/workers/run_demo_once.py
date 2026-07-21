"""Run one fully guarded MT5 demo cycle.

This module refuses live accounts and requires three independent configuration
gates. It must only be launched after shadow and simulation verification.
"""
import json
import time
from datetime import UTC, datetime
from decimal import ROUND_DOWN, Decimal
from sqlalchemy import select

from app.agents.erwin.service import CommanderErwinService
from app.agents.annie.models import NewsRiskStatus
from app.agents.mikasa.models import TradingPermission
from app.application.avenger import AvengerBracketBuilder
from app.application.execution import DemoExecutionService
from app.application.position_sizing import PositionSizer
from app.application.workflows.decision_preview import DecisionPreview
from app.config.settings import get_settings
from app.domain.journal.repository import TradeJournalRepository
from app.domain.trading.models import PositionSizeResult, ProposalStatus, RiskProfile, SymbolSpecification
from app.infrastructure.market_data.factory import build_economic_calendar_provider
from app.infrastructure.mt5.gateway import MetaTrader5Gateway
from app.infrastructure.persistence.database import SessionLocal
from app.infrastructure.persistence.models import AlertRecord, ExecutionAttemptRecord
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


def _confirm_broker_protection(gateway: MetaTrader5Gateway, proposal, ticket: str) -> None:
    """Demo fills must keep broker-side protection visible in MT5."""
    matched_position = None
    for _ in range(5):
        positions = gateway.get_positions(proposal.symbol)
        matched_position = next(
            (
                position for position in positions
                if position.ticket == ticket or (position.side == proposal.side.value and position.volume == proposal.volume)
            ),
            None,
        )
        if matched_position is not None:
            break
        time.sleep(0.5)
    if matched_position is None:
        raise RuntimeError(f"Unable to confirm broker-side position protection after demo submit ticket={ticket}")
    if matched_position.stop_loss is not None and matched_position.take_profit is not None:
        return
    close_ticket = gateway.close_position(matched_position, "xau-manager:missing-protection")
    raise RuntimeError(
        f"Demo position {matched_position.ticket} lacked broker SL/TP after entry; emergency close sent as {close_ticket}"
    )


def _managed_avenger_orders(gateway: MetaTrader5Gateway) -> tuple:
    get_orders = getattr(gateway, "get_orders", None)
    if not callable(get_orders):
        return ()
    return tuple(
        order
        for order in get_orders("XAUUSD")
        if (order.comment or "").startswith("xau-avenger:") or order.magic == 260713
    )


def _record_avenger_attempt(session, proposal, ticket: str, risk_amount: Decimal) -> None:
    attempt = session.scalar(
        select(ExecutionAttemptRecord).where(ExecutionAttemptRecord.proposal_id == proposal.id)
    )
    if attempt:
        attempt.status = "SUBMITTED"
        attempt.broker_ticket = ticket
        attempt.entry_price = proposal.entry_price
        attempt.initial_stop_loss = proposal.stop_loss
        attempt.initial_take_profit = proposal.take_profit
        attempt.initial_risk_price = abs(proposal.entry_price - proposal.stop_loss)
        attempt.initial_risk_usd = risk_amount
        attempt.intended_reward_risk = proposal.reward_risk_ratio()
        attempt.volume = proposal.volume


def _run_avenger_bracket(
    preview: DecisionPreview,
    gateway: MetaTrader5Gateway,
    profile: RiskProfile,
    settings,
    repository: TradeJournalRepository,
) -> str:
    if preview.market is None:
        raise RuntimeError("Avenger bracket requires a market snapshot")
    if preview.annie.status is not NewsRiskStatus.SAFE:
        with SessionLocal() as session:
            repository.record_preview(session, preview)
            repository.record_collective_events(
                session,
                preview.correlation_id,
                (
                    (
                        6,
                        "EXECUTION",
                        "NO_ORDER",
                        json.dumps({"reason": "Annie information-risk block"}),
                    ),
                ),
            )
            repository.record_heartbeat(
                session, "demo-worker", "HEALTHY", "Avenger bracket blocked by Annie"
            )
        return "NO_ORDER"
    if preview.mikasa.hard_blocked or preview.mikasa.permission is TradingPermission.WAIT:
        with SessionLocal() as session:
            repository.record_preview(session, preview)
            repository.record_collective_events(
                session,
                preview.correlation_id,
                ((6, "EXECUTION", "NO_ORDER", json.dumps({"reason": preview.mikasa.reasons})),),
            )
            repository.record_heartbeat(
                session, "demo-worker", "HEALTHY", "Avenger bracket blocked by Mikasa hard gate"
            )
        return "NO_ORDER"

    gateway.connect()
    try:
        account = gateway.get_account_snapshot()
        if gateway.get_positions("XAUUSD") or _managed_avenger_orders(gateway):
            with SessionLocal() as session:
                repository.record_preview(session, preview)
                repository.record_collective_events(
                    session,
                    preview.correlation_id,
                    (
                        (
                            6,
                            "EXECUTION",
                            "NO_ORDER",
                            json.dumps(
                                {
                                    "reason": (
                                        "Avenger waits for flat exposure and no "
                                        "managed pending orders"
                                    )
                                }
                            ),
                        ),
                    ),
                )
                repository.record_heartbeat(
                    session,
                    "demo-worker",
                    "HEALTHY",
                    "Avenger bracket skipped: exposure already active",
                )
            return "NO_ORDER_ACTIVE_EXPOSURE"
        with SessionLocal() as session:
            execution_locked = repository.has_critical_execution_incident(session)
        plan = AvengerBracketBuilder().build(
            preview.market,
            settings,
            profile.risk_per_trade_pct,
            preview.correlation_id,
        )
        spread = plan.spread
        erwin = CommanderErwinService()
        buy_decision = erwin.evaluate(
            plan.buy.proposal, account, profile, spread, execution_locked=execution_locked
        )
        sell_decision = erwin.evaluate(
            plan.sell.proposal, account, profile, spread, execution_locked=execution_locked
        )
        with SessionLocal() as session:
            repository.record_preview(session, preview)
            repository.record_collective_events(
                session,
                preview.correlation_id,
                (
                    (
                        6,
                        "EREN",
                        "AVENGER_BRACKET_PROPOSAL",
                        json.dumps(
                            {
                                "profile": plan.profile_name,
                                "symbol": plan.symbol,
                                "effective_trigger": str(plan.effective_trigger),
                                "spread": str(plan.spread),
                                "trail_distance": str(plan.trail_distance),
                                "expires_at": plan.expires_at.isoformat(),
                                "buy": plan.buy.proposal.model_dump(mode="json"),
                                "sell": plan.sell.proposal.model_dump(mode="json"),
                            }
                        ),
                    ),
                    (
                        7,
                        "COMMANDER_ERWIN",
                        "AVENGER_BUY_RISK_DECISION",
                        buy_decision.model_dump_json(),
                    ),
                    (
                        8,
                        "COMMANDER_ERWIN",
                        "AVENGER_SELL_RISK_DECISION",
                        sell_decision.model_dump_json(),
                    ),
                ),
            )
        if (
            buy_decision.status is not ProposalStatus.APPROVED
            or sell_decision.status is not ProposalStatus.APPROVED
        ):
            with SessionLocal() as session:
                repository.record_collective_events(
                    session,
                    preview.correlation_id,
                    (
                        (
                            9,
                            "EXECUTION",
                            "NO_ORDER",
                            json.dumps(
                                {"buy": buy_decision.reasons, "sell": sell_decision.reasons}
                            ),
                        ),
                    ),
                )
                repository.record_heartbeat(
                    session,
                    "demo-worker",
                    "HEALTHY",
                    "Erwin rejected Avenger bracket; no pending orders",
                )
            return "NO_ORDER"
        risk_amount = account.equity * profile.risk_per_trade_pct / Decimal("100")
        with SessionLocal() as session:
            for proposal in (plan.buy.proposal, plan.sell.proposal):
                existing = session.scalar(
                    select(ExecutionAttemptRecord).where(
                        ExecutionAttemptRecord.proposal_id == proposal.id
                    )
                )
                if existing is not None:
                    repository.record_heartbeat(
                        session,
                        "demo-worker",
                        "ERROR",
                        "Duplicate Avenger bracket submission blocked",
                    )
                    return "NO_ORDER_DUPLICATE_BLOCKED"
                session.add(
                    ExecutionAttemptRecord(
                        proposal_id=proposal.id,
                        correlation_id=proposal.correlation_id,
                        status="CLAIMED",
                    )
                )
            session.commit()
        try:
            tickets = DemoExecutionService(gateway, True, "demo").submit_bracket(
                plan, buy_decision, sell_decision
            )
        except Exception as exc:
            with SessionLocal() as session:
                for proposal in (plan.buy.proposal, plan.sell.proposal):
                    attempt = session.scalar(
                        select(ExecutionAttemptRecord).where(
                            ExecutionAttemptRecord.proposal_id == proposal.id
                        )
                    )
                    if attempt:
                        attempt.status = "UNKNOWN_RECONCILE"
                        attempt.error_type = type(exc).__name__
                session.add(
                    AlertRecord(
                        severity="CRITICAL",
                        message=(
                            "Avenger bracket blocked pending broker reconciliation: "
                            f"{type(exc).__name__}"
                        ),
                    )
                )
                session.commit()
                repository.record_heartbeat(
                    session,
                    "demo-worker",
                    "ERROR",
                    "Avenger bracket outcome unknown; reconciliation required",
                )
            raise
        buy_ticket, sell_ticket = tickets.split(",", 1)
        with SessionLocal() as session:
            _record_avenger_attempt(session, plan.buy.proposal, buy_ticket, risk_amount)
            _record_avenger_attempt(session, plan.sell.proposal, sell_ticket, risk_amount)
            session.commit()
            repository.record_collective_events(
                session,
                preview.correlation_id,
                (
                    (
                        9,
                        "EXECUTION",
                        "AVENGER_BRACKET_SUBMITTED",
                        json.dumps(
                            {
                                "profile": plan.profile_name,
                                "buy_ticket": buy_ticket,
                                "sell_ticket": sell_ticket,
                                "methodology": (
                                    "TradingBot Master Avenger pending "
                                    "buy-stop/sell-stop bracket"
                                ),
                            }
                        ),
                    ),
                ),
            )
            repository.record_heartbeat(
                session, "demo-worker", "HEALTHY", f"Avenger bracket submitted: {tickets}"
            )
        return tickets
    finally:
        gateway.shutdown()


def run_once() -> str:
    settings = get_settings()
    if settings.trading_mode != "demo":
        raise RuntimeError("Demo worker refuses non-demo trading mode")
    if not settings.execution_enabled or not settings.demo_trading_confirmed:
        raise RuntimeError("Demo execution requires XAU_EXECUTION_ENABLED and XAU_DEMO_TRADING_CONFIRMED")
    if not settings.demo_entry_enabled:
        raise RuntimeError("Demo entry worker disabled during position-manager validation")
    if settings.kill_switch_active:
        raise RuntimeError("Demo execution blocked by XAU_KILL_SWITCH_ACTIVE")

    repository = TradeJournalRepository()
    with SessionLocal() as session:
        repository.record_heartbeat(session, "demo-worker", "RUNNING", "Guarded demo cycle started")
    profile = _profile(settings)
    observation_active = bool(settings.observation_mode_until and datetime.now(UTC) < settings.observation_mode_until)
    exploration_active = bool(settings.demo_exploration_enabled)
    minimum_market_quality = Decimal(str(settings.demo_exploration_min_market_quality)) if exploration_active else Decimal(str(settings.observation_min_market_quality)) if observation_active else Decimal("7.00")
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
        minimum_market_quality,
        observation_active or exploration_active,
        exploration_trade_when_flat=exploration_active,
    )

    if settings.demo_strategy_engine == "AVENGER_STRADDLE":
        return _run_avenger_bracket(preview, gateway, profile, settings, repository)

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
        try:
            sized = PositionSizer().size(preview.eren, account.equity, specification)
            proposal = preview.eren.model_copy(update={"volume": sized.volume})
        except ValueError:
            if not exploration_active:
                raise
            stop_distance = abs(preview.eren.entry_price - preview.eren.stop_loss)
            risk_amount = Decimal(str(specification.volume_min)) * stop_distance * Decimal(str(specification.trade_contract_size))
            actual_risk_pct = (risk_amount / account.equity * Decimal("100")).quantize(Decimal("0.0001"))
            sized = PositionSizeResult(volume=Decimal(str(specification.volume_min)), risk_amount=risk_amount, stop_distance=stop_distance)
            proposal = preview.eren.model_copy(update={
                "volume": Decimal(str(specification.volume_min)),
                "expected_risk_pct": actual_risk_pct,
                "reasons": (*preview.eren.reasons, "Demo exploration used broker-minimum volume so the bot can collect real execution evidence"),
            })
        with SessionLocal() as session:
            execution_locked = repository.has_critical_execution_incident(session)
        tick = gateway.get_tick("XAUUSD")
        decision = CommanderErwinService().evaluate(proposal, account, profile, tick.ask - tick.bid, execution_locked=execution_locked)
        if decision.status is ProposalStatus.APPROVED and decision.recommended_size_multiplier < Decimal("1"):
            raw_volume = proposal.volume * decision.recommended_size_multiplier
            adjusted_volume = (raw_volume / specification.volume_step).to_integral_value(rounding=ROUND_DOWN) * specification.volume_step
            if adjusted_volume < specification.volume_min:
                if exploration_active:
                    proposal = proposal.model_copy(update={
                        "volume": Decimal(str(specification.volume_min)),
                        "reasons": (*proposal.reasons, "Demo exploration retained broker-minimum volume despite Erwin's reduced-size preference"),
                    })
                    decision = decision.model_copy(update={
                        "risk_posture": "DEMO_EXPLORATION_MINIMUM_LOT",
                        "reasons": ("Demo exploration retained broker-minimum volume to collect execution evidence", *decision.reasons),
                    })
                else:
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
            if repository.has_critical_execution_incident(session):
                repository.append_event(session, proposal.correlation_id, "EXECUTION", "EXECUTION_LOCKED_ORDER_BLOCKED", {
                    "proposal_id": str(proposal.id),
                    "execution_authority": False,
                    "reason": "Unresolved critical execution incident",
                })
                repository.record_heartbeat(session, "demo-worker", "ERROR", "Demo order blocked: EXECUTION LOCKED")
                return "NO_ORDER_EXECUTION_LOCKED"
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
            _confirm_broker_protection(gateway, proposal, ticket)
        except Exception as exc:
            with SessionLocal() as session:
                attempt = session.scalar(select(ExecutionAttemptRecord).where(ExecutionAttemptRecord.proposal_id == proposal.id))
                if attempt:
                    attempt.status = "UNKNOWN_RECONCILE"; attempt.error_type = type(exc).__name__
                session.add(AlertRecord(severity="CRITICAL", message=f"Demo entry blocked pending broker reconciliation: {type(exc).__name__}"))
                session.commit()
                repository.append_event(session, proposal.correlation_id, "EXECUTION", "DEMO_ORDER_STATUS_UNKNOWN", {
                    "proposal_id": str(proposal.id), "error_type": type(exc).__name__,
                    "message": "Automatic retry blocked pending broker reconciliation",
                })
                repository.record_heartbeat(session, "demo-worker", "ERROR", "Demo order outcome unknown; reconciliation required")
            raise
        with SessionLocal() as session:
            attempt = session.scalar(select(ExecutionAttemptRecord).where(ExecutionAttemptRecord.proposal_id == proposal.id))
            if attempt:
                attempt.status = "SUBMITTED"
                attempt.broker_ticket = ticket
                attempt.entry_price = proposal.entry_price
                attempt.initial_stop_loss = proposal.stop_loss
                attempt.initial_take_profit = proposal.take_profit
                attempt.initial_risk_price = abs(proposal.entry_price - proposal.stop_loss)
                attempt.initial_risk_usd = sized.risk_amount
                attempt.intended_reward_risk = proposal.reward_risk_ratio()
                attempt.volume = proposal.volume
                session.commit()
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
