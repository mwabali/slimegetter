from datetime import UTC, datetime, timedelta
from decimal import Decimal
import json
import shutil
from pathlib import Path

import asyncio
from collections import defaultdict

from fastapi import APIRouter, Depends, HTTPException, WebSocket, WebSocketDisconnect
from sqlalchemy.orm import Session
from sqlalchemy import func, select
from sqlalchemy.exc import SQLAlchemyError
from pydantic import BaseModel, Field

from app.agents.erwin.service import CommanderErwinService
from app.agents.armin.service import ArminService, TradeOutcome
from app.agents.levi.service import LeviReview, LeviService
from app.agents.annie.service import AnnieService
from app.agents.annie.models import AnnieNewsReport
from app.api.auth import Role, require_role
from app.application.event_bus import mission_events
from app.application.workflows.decision_preview import (
    DecisionPreview,
    DecisionPreviewRequest,
    DecisionPreviewWorkflow,
)
from app.domain.journal.models import DecisionTimelineEvent
from app.domain.dashboard.models import AccountDashboardSnapshot, AgentDashboardStatus, BrokerClosedPositionDashboardItem, ChartBar, ChartMarker, ChartResponse, ClosedTradeDashboardItem, CycleDashboardSummary, FillDashboardItem, HealthState, JournalPage, LearningDashboardResponse, PlatformMode, PositionDashboardItem, ServiceHealth, SimulatedPositionDashboardItem, StrategyRanking, StrategyRegistryItem, SymbolDashboardSnapshot, SystemStatusResponse
from app.domain.trading.models import AccountSnapshot, RiskDecision, RiskProfile, TradeProposal
from app.domain.journal.repository import TradeJournalRepository
from app.infrastructure.persistence.database import get_session
from app.infrastructure.news.rss_search import GoogleNewsRssSearch
from app.config.settings import get_settings
from app.infrastructure.mt5.gateway import MetaTrader5Gateway, Mt5AdapterError
from app.infrastructure.persistence.models import AlertRecord, ClosedTradeRecord, ExecutionIncidentRecord, ExperimentRecord, ResearchProposalRecord, SimulatedPositionRecord, StrategyRecord
from app.application.mt5_sync import Mt5ReadOnlySynchronizer
from app.application.backtesting import BacktestResult, run_ema_rsi_backtest
from app.strategies.catalog import CATALOG, StrategySpec
from app.strategies.coverage import build_coverage_plan, coverage_status

router = APIRouter()
_erwin = CommanderErwinService()
_journal = TradeJournalRepository()
_preview_workflow = DecisionPreviewWorkflow()
_annie = AnnieService()
_armin = ArminService()
_mt5_sync = Mt5ReadOnlySynchronizer()


class StrategyRegistrationRequest(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    version: str = Field(min_length=1, max_length=64)
    config: dict[str, object] = Field(default_factory=dict)


class StrategyPromotionRequest(BaseModel):
    notes: str = Field(min_length=1, max_length=2000)


class LeviReviewRequest(BaseModel):
    journal_context: str = Field(min_length=1, max_length=50000)


class ExperimentRequest(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    proposal: dict[str, object] = Field(default_factory=dict)


class ExperimentStatusRequest(BaseModel):
    status: str = Field(pattern="^(PROPOSED|RUNNING|COMPLETED|REJECTED)$")


class AlertRequest(BaseModel):
    severity: str = Field(pattern="^(INFO|WARNING|CRITICAL)$")
    message: str = Field(min_length=1, max_length=2000)


class IncidentResolveRequest(BaseModel):
    resolved_by: str = Field(min_length=2, max_length=128)
    resolution_note: str = Field(min_length=3, max_length=2000)


@router.get("/health", tags=["operations"])
def health() -> dict[str, str]:
    settings = get_settings()
    return {"status": "ok", "execution": "enabled" if settings.execution_enabled else "disabled"}


@router.get("/system/status", response_model=SystemStatusResponse, tags=["dashboard"])
def system_status(session: Session = Depends(get_session)) -> SystemStatusResponse:
    """Read-only dashboard status. Unknown is deliberate when a worker has not reported state."""
    now = datetime.now(UTC); settings = get_settings()
    execution_locked = _journal.has_critical_execution_incident(session)
    mode = PlatformMode.READ_ONLY_SHADOW_MODE if not settings.execution_enabled else PlatformMode.DEMO_EXECUTION
    mt5_health = ServiceHealth(state=HealthState.UNKNOWN, message="MT5 worker status unavailable", checked_at=now)
    mt5_permissions: dict[str, bool | None] = {
        "terminal_trade_allowed": None,
        "account_trade_allowed": None,
        "account_trade_expert": None,
    }
    try:
        gateway = MetaTrader5Gateway.from_installed_package(allow_orders=False); gateway.connect(); gateway.get_tick("XAUUSD")
        mt5_permissions = gateway.terminal_permissions()
        gateway.shutdown()
        terminal_flag = mt5_permissions.get("terminal_trade_allowed")
        if settings.execution_enabled and terminal_flag is False:
            mt5_health = ServiceHealth(state=HealthState.DEGRADED, message="Connected to demo terminal, but MT5 AutoTrading is off", checked_at=now)
        else:
            mt5_health = ServiceHealth(state=HealthState.HEALTHY, message="Connected to demo terminal; read-only", checked_at=now)
    except Exception as exc:
        mt5_health = ServiceHealth(state=HealthState.UNAVAILABLE, message=f"MT5 unavailable: {type(exc).__name__}", checked_at=now)
    worker_name = "demo-worker" if settings.execution_enabled else "shadow-worker"
    worker_health = ServiceHealth(state=HealthState.UNKNOWN, message=f"{worker_name} has not reported", checked_at=now)
    journal_health = ServiceHealth(state=HealthState.HEALTHY, message="Dashboard journal query available", checked_at=now)
    try:
        heartbeat = _journal.latest_heartbeat(session, worker_name)
    except SQLAlchemyError as exc:
        # A missing/outdated migration must degrade observability, not crash the
        # entire Mission Control status endpoint.  No schema is mutated here.
        heartbeat = None
        worker_health = ServiceHealth(state=HealthState.UNKNOWN, message=f"{worker_name} status unavailable until journal migrations are applied", checked_at=now)
        journal_health = ServiceHealth(state=HealthState.DEGRADED, message=f"Journal schema unavailable: {type(exc).__name__}", checked_at=now)
    if heartbeat:
        last_seen = heartbeat.last_seen_at
        if last_seen.tzinfo is None:
            last_seen = last_seen.replace(tzinfo=UTC)
        age = (now - last_seen).total_seconds()
        worker_health = ServiceHealth(state=HealthState.HEALTHY if heartbeat.status == "HEALTHY" and age < 900 else HealthState.DEGRADED, message=heartbeat.message, checked_at=last_seen)
    strategy_worker = ServiceHealth(state=HealthState.UNKNOWN, message="strategy-shadow-worker has not reported", checked_at=now)
    try:
        strategy_heartbeat = _journal.latest_heartbeat(session, "strategy-shadow-worker")
    except SQLAlchemyError:
        strategy_heartbeat = None
    if strategy_heartbeat:
        strategy_seen = strategy_heartbeat.last_seen_at
        if strategy_seen.tzinfo is None: strategy_seen = strategy_seen.replace(tzinfo=UTC)
        strategy_age = (now - strategy_seen).total_seconds()
        strategy_worker = ServiceHealth(state=HealthState.HEALTHY if strategy_heartbeat.status == "HEALTHY" and strategy_age < 900 else HealthState.DEGRADED, message=strategy_heartbeat.message, checked_at=strategy_seen)
    simulation_worker = ServiceHealth(state=HealthState.UNKNOWN, message="simulation-worker has not reported", checked_at=now)
    try:
        simulation_heartbeat = _journal.latest_heartbeat(session, "simulation-worker")
    except SQLAlchemyError:
        simulation_heartbeat = None
    if simulation_heartbeat:
        simulation_seen = simulation_heartbeat.last_seen_at
        if simulation_seen.tzinfo is None: simulation_seen = simulation_seen.replace(tzinfo=UTC)
        simulation_age = (now - simulation_seen).total_seconds()
        simulation_worker = ServiceHealth(state=HealthState.HEALTHY if simulation_heartbeat.status == "HEALTHY" and simulation_age < 900 else HealthState.DEGRADED, message=simulation_heartbeat.message, checked_at=simulation_seen)
    if not settings.demo_position_manager_enabled:
        position_manager = ServiceHealth(state=HealthState.DISABLED, message="Pixis disabled by configuration", checked_at=now)
    else:
        position_manager = ServiceHealth(state=HealthState.UNKNOWN, message="Pixis has not reported", checked_at=now)
        try:
            position_heartbeat = _journal.latest_heartbeat(session, "demo-position-manager")
        except SQLAlchemyError:
            position_heartbeat = None
        if position_heartbeat:
            position_seen = position_heartbeat.last_seen_at
            if position_seen.tzinfo is None: position_seen = position_seen.replace(tzinfo=UTC)
            position_age = (now - position_seen).total_seconds()
            position_manager = ServiceHealth(state=HealthState.HEALTHY if position_heartbeat.status == "HEALTHY" and position_age < max(10, settings.demo_position_poll_seconds * 4) else HealthState.DEGRADED, message=position_heartbeat.message, checked_at=position_seen)
    free_disk_gb = shutil.disk_usage(".").free / (1024 ** 3)
    disk_health = ServiceHealth(state=HealthState.HEALTHY if free_disk_gb >= 1 else HealthState.DEGRADED, message=f"{free_disk_gb:.1f} GiB free", checked_at=now)
    levi_health = ServiceHealth(
        state=HealthState.DISABLED if not settings.levi_enabled else HealthState.HEALTHY if settings.openai_api_key else HealthState.DEGRADED,
        message="Disabled by configuration" if not settings.levi_enabled else "API credential configured" if settings.openai_api_key else "Enabled, but no API credential is configured",
        checked_at=now,
    )
    news_health = ServiceHealth(state=HealthState.DEGRADED, message="Official BLS calendar is queried by the worker; Fed/manual lockouts still require verification", checked_at=now)
    return SystemStatusResponse(
        platform_mode=mode, execution_enabled=settings.execution_enabled, kill_switch_active=settings.kill_switch_active,
        execution_locked=execution_locked,
        demo_exploration_enabled=settings.demo_exploration_enabled,
        mt5_terminal_trade_allowed=mt5_permissions.get("terminal_trade_allowed"),
        mt5_account_trade_allowed=mt5_permissions.get("account_trade_allowed"),
        mt5_account_expert_allowed=mt5_permissions.get("account_trade_expert"),
        mt5=mt5_health, shadow_worker=worker_health, journal=journal_health,
        websocket=ServiceHealth(state=HealthState.HEALTHY, message="API event stream enabled; worker events reconcile from the journal", checked_at=now),
        news=news_health, strategy_shadow_worker=strategy_worker, simulation_worker=simulation_worker,
        demo_position_manager=position_manager, database=journal_health,
        calendar=news_health, levi=levi_health,
        backtester=ServiceHealth(state=HealthState.HEALTHY, message="Deterministic backtest service loaded", checked_at=now),
        disk=disk_health,
    )


@router.get("/mt5/account", response_model=AccountDashboardSnapshot, tags=["dashboard"])
def mt5_account() -> AccountDashboardSnapshot:
    settings = get_settings()
    gateway = MetaTrader5Gateway.from_installed_package(allow_orders=False)
    gateway.connect()
    try:
        account = gateway.get_account_snapshot()
        return AccountDashboardSnapshot(
            account_type="DEMO",
            balance=float(account.balance or account.equity),
            equity=float(account.equity),
            free_margin=float(account.free_margin),
            used_margin=float(account.used_margin) if account.used_margin is not None else None,
            margin_level=float(account.margin_level) if account.margin_level is not None else None,
            floating_pnl=float(account.floating_pnl) if account.floating_pnl is not None else None,
            currency=account.currency,
            leverage=account.leverage,
            current_exposure_pct=float(account.current_exposure_pct),
            realized_daily_pnl=float(account.realized_daily_pnl),
            realized_weekly_pnl=float(account.realized_weekly_pnl),
            open_position_count=account.open_position_count,
            configured_risk_per_trade_pct=float(settings.max_risk_per_trade_pct),
            maximum_daily_loss_pct=float(settings.max_daily_loss_pct),
            maximum_weekly_loss_pct=float(settings.max_weekly_loss_pct),
            execution_permission="ENABLED" if settings.execution_enabled and not settings.kill_switch_active else "BLOCKED",
        )
    finally:
        gateway.shutdown()


@router.get("/mt5/symbols/xauusd", response_model=SymbolDashboardSnapshot, tags=["dashboard"])
def mt5_xauusd() -> SymbolDashboardSnapshot:
    gateway = MetaTrader5Gateway.from_installed_package(allow_orders=False)
    gateway.connect()
    try:
        tick = gateway.get_tick("XAUUSD")
        return SymbolDashboardSnapshot(symbol="XAUUSD", bid=float(tick.bid) or None, ask=float(tick.ask) or None, spread=float(tick.ask - tick.bid) if tick.ask and tick.bid else None, tick_time_msc=tick.time_msc or None)
    finally:
        gateway.shutdown()


@router.get("/mt5/positions", response_model=tuple[PositionDashboardItem, ...], tags=["dashboard"])
def mt5_positions(session: Session = Depends(get_session)) -> tuple[PositionDashboardItem, ...]:
    """Read and persist current MT5 positions; never sends an order."""
    settings = get_settings()
    gateway = MetaTrader5Gateway.from_installed_package(allow_orders=False)
    gateway.connect()
    try:
        positions = gateway.get_positions()
        _mt5_sync.sync_positions(session, positions)
        state_path = Path(settings.demo_position_state_path)
        manager_state: dict[str, dict[str, object]] = {}
        if state_path.exists():
            try:
                loaded = json.loads(state_path.read_text(encoding="utf-8"))
                manager_state = loaded if isinstance(loaded, dict) else {}
            except (OSError, json.JSONDecodeError):
                manager_state = {}

        def parse_dt(value: object) -> datetime | None:
            if not value:
                return None
            try:
                parsed = datetime.fromisoformat(str(value))
                return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)
            except ValueError:
                return None

        execution_locked = _journal.has_critical_execution_incident(session)
        items = []
        for p in positions:
            memory = manager_state.get(p.ticket, {})
            items.append(PositionDashboardItem(
                ticket=p.ticket, symbol=p.symbol, side=p.side, volume=float(p.volume), price_open=float(p.price_open),
                stop_loss=float(p.stop_loss) if p.stop_loss is not None else None,
                take_profit=float(p.take_profit) if p.take_profit is not None else None,
                profit=float(p.profit), opened_at=p.opened_at,
                estimated_net_profit=float(memory.get("estimated_net_profit", p.profit)),
                initial_risk_usd=float(memory["initial_risk_usd"]) if memory.get("initial_risk_usd") else None,
                current_r=float(memory["current_r"]) if memory.get("current_r") else None,
                peak_profit=float(memory["peak_profit"]) if memory.get("peak_profit") is not None else None,
                peak_r=float(memory["peak_r"]) if memory.get("peak_r") else None,
                active_exit_policy=str(memory.get("active_exit_policy") or settings.demo_position_exit_policy),
                profit_management_state=str(memory.get("status") or "MONITORING"),
                breakeven_level=float(memory["breakeven_level"]) if memory.get("breakeven_level") else None,
                locked_profit_floor=float(memory["locked_profit_floor"]) if memory.get("locked_profit_floor") else None,
                trailing_floor=float(memory["trailing_floor"]) if memory.get("trailing_floor") else None,
                allowed_giveback=float(memory["allowed_giveback"]) if memory.get("allowed_giveback") else None,
                last_sl_modified_at=parse_dt(memory.get("last_sl_modified_at")),
                close_attempt_count=int(memory.get("close_attempt_count", 0)),
                pending_exit_reason=str(memory["pending_exit_reason"]) if memory.get("pending_exit_reason") else None,
                latest_mt5_error=str(memory["latest_mt5_error"]) if memory.get("latest_mt5_error") else None,
                cooldown_reason=str(memory["cooldown_reason"]) if memory.get("cooldown_reason") else None,
                next_retry_after=parse_dt(memory.get("next_retry_after")),
                execution_locked=execution_locked,
            ))
        return tuple(items)
    finally:
        gateway.shutdown()


@router.get("/simulation/positions", response_model=tuple[SimulatedPositionDashboardItem, ...], tags=["dashboard", "simulation"])
def simulated_positions(session: Session = Depends(get_session)) -> tuple[SimulatedPositionDashboardItem, ...]:
    """Read the paper-only ledger; this endpoint has no execution controls."""
    rows = session.scalars(select(SimulatedPositionRecord).order_by(SimulatedPositionRecord.opened_at.desc())).all()
    return tuple(SimulatedPositionDashboardItem(
        id=row.id, correlation_id=row.correlation_id, strategy_version=row.strategy_version,
        symbol=row.symbol, side=row.side, volume=float(row.volume), entry_price=float(row.entry_price),
        stop_loss=float(row.stop_loss), take_profit=float(row.take_profit),
        exit_price=float(row.exit_price) if row.exit_price is not None else None,
        pnl=float(row.pnl) if row.pnl is not None else None, status=row.status,
        close_reason=row.close_reason, opened_at=row.opened_at, closed_at=row.closed_at,
    ) for row in rows)


@router.get("/mt5/fills", response_model=tuple[FillDashboardItem, ...], tags=["dashboard"])
def mt5_fills(hours: int = 24, session: Session = Depends(get_session)) -> tuple[FillDashboardItem, ...]:
    """Read and persist recent MT5 deals for audit and closed-trade processing."""
    settings = get_settings()
    gateway = MetaTrader5Gateway.from_installed_package(allow_orders=False)
    gateway.connect()
    try:
        since = datetime.now(UTC) - timedelta(hours=max(1, min(hours, 24 * 30)))
        until = datetime.now(UTC) + timedelta(hours=settings.mt5_server_utc_offset_hours)
        fills = gateway.get_recent_fills(since, until)
        _mt5_sync.sync_fills(session, fills)
        return tuple(FillDashboardItem(deal_ticket=f.deal_ticket, order_ticket=f.order_ticket, symbol=f.symbol, side=f.side, volume=float(f.volume), price=float(f.price), profit=float(f.profit), filled_at=f.filled_at) for f in fills)
    finally:
        gateway.shutdown()


@router.get("/mt5/closed-trades", response_model=tuple[ClosedTradeDashboardItem, ...], tags=["dashboard"])
def mt5_closed_trades(hours: int = 24 * 30, session: Session = Depends(get_session)) -> tuple[ClosedTradeDashboardItem, ...]:
    settings = get_settings()
    gateway = MetaTrader5Gateway.from_installed_package(allow_orders=False)
    gateway.connect()
    try:
        since = datetime.now(UTC) - timedelta(hours=max(1, min(hours, 24 * 365)))
        until = datetime.now(UTC) + timedelta(hours=settings.mt5_server_utc_offset_hours)
        _mt5_sync.sync_fills(session, gateway.get_recent_fills(since, until))
        rows = session.scalars(select(ClosedTradeRecord).order_by(ClosedTradeRecord.closed_at.desc())).all()
        return tuple(ClosedTradeDashboardItem(strategy_version=row.strategy_version, session=row.session, pnl=float(row.pnl), reward_risk=float(row.reward_risk), source_deal_ticket=row.source_deal_ticket, closed_at=row.closed_at) for row in rows)
    finally:
        gateway.shutdown()


@router.get("/mt5/closed-positions", response_model=tuple[BrokerClosedPositionDashboardItem, ...], tags=["dashboard"])
def mt5_closed_positions(hours: int = 24 * 30) -> tuple[BrokerClosedPositionDashboardItem, ...]:
    """Reconstruct broker-visible closed positions from MT5 deals by position id."""
    settings = get_settings()
    gateway = MetaTrader5Gateway.from_installed_package(allow_orders=False)
    gateway.connect()
    try:
        since = datetime.now(UTC) - timedelta(hours=max(1, min(hours, 24 * 365)))
        until = datetime.now(UTC) + timedelta(hours=settings.mt5_server_utc_offset_hours)
        raw = gateway._mt5.history_deals_get(since, until)  # type: ignore[attr-defined]
        if raw is None:
            return ()
        deals_by_position: dict[str, list[object]] = defaultdict(list)
        for deal in raw:
            if str(getattr(deal, "symbol", "")).upper() != "XAUUSD":
                continue
            position_id = str(getattr(deal, "position_id", "") or "")
            if not position_id:
                continue
            deals_by_position[position_id].append(deal)
        output: list[BrokerClosedPositionDashboardItem] = []
        for position_id, deals in deals_by_position.items():
            entries = [deal for deal in deals if getattr(deal, "entry", None) == gateway._mt5.DEAL_ENTRY_IN]  # type: ignore[attr-defined]
            exits = [deal for deal in deals if getattr(deal, "entry", None) in {gateway._mt5.DEAL_ENTRY_OUT, gateway._mt5.DEAL_ENTRY_OUT_BY}]  # type: ignore[attr-defined]
            if not entries or not exits:
                continue
            entry, exit_deal = entries[0], exits[-1]
            side = "BUY" if getattr(entry, "type", None) == gateway._mt5.DEAL_TYPE_BUY else "SELL"  # type: ignore[attr-defined]
            output.append(BrokerClosedPositionDashboardItem(
                position_id=position_id, symbol=str(getattr(entry, "symbol", "XAUUSD")), side=side,
                volume=float(getattr(entry, "volume", 0) or 0), entry_price=float(getattr(entry, "price", 0) or 0),
                exit_price=float(getattr(exit_deal, "price", 0) or 0), pnl=float(getattr(exit_deal, "profit", 0) or 0),
                opened_at=datetime.fromtimestamp(int(getattr(entry, "time", 0)), UTC),
                closed_at=datetime.fromtimestamp(int(getattr(exit_deal, "time", 0)), UTC),
                entry_deal_ticket=str(getattr(entry, "ticket", "")),
                exit_deal_ticket=str(getattr(exit_deal, "ticket", "")),
                close_order_ticket=str(getattr(exit_deal, "order", "")) if getattr(exit_deal, "order", 0) else None,
            ))
        return tuple(sorted(output, key=lambda item: item.closed_at, reverse=True))
    finally:
        gateway.shutdown()


@router.get("/backtest/xauusd", response_model=BacktestResult, tags=["armin"])
def backtest_xauusd(count: int = 500, strategy_version: str = "ema-rsi@1.0") -> BacktestResult:
    """Run a deterministic research backtest on read-only MT5 M5 history."""
    gateway = MetaTrader5Gateway.from_installed_package(allow_orders=False)
    gateway.connect()
    try:
        bars = gateway.get_recent_bars("XAUUSD", max(40, min(count, 5000)))
        return run_ema_rsi_backtest(bars, strategy_version)
    finally:
        gateway.shutdown()


@router.get("/mt5/chart/xauusd", response_model=ChartResponse, tags=["dashboard"])
def mt5_xauusd_chart(count: int = 120, session: Session = Depends(get_session)) -> ChartResponse:
    gateway = MetaTrader5Gateway.from_installed_package(allow_orders=False)
    gateway.connect()
    try:
        bars = gateway.get_recent_bars("XAUUSD", max(30, min(count, 500)))
        cycle = _journal.latest_cycle(session)
        markers = ()
        if cycle:
            events = _journal.timeline(session, cycle.correlation_id)
            markers = tuple(ChartMarker(timestamp=event.created_at, label=f"{event.agent_name}: {event.event_type}", marker_type=event.event_type, correlation_id=event.correlation_id, sequence=event.sequence) for event in events)
        return ChartResponse(symbol="XAUUSD", bars=tuple(ChartBar(timestamp=bar.time, open=float(bar.open), high=float(bar.high), low=float(bar.low), close=float(bar.close)) for bar in bars), markers=markers)
    finally:
        gateway.shutdown()


@router.get("/cycles/current", response_model=CycleDashboardSummary | None, tags=["dashboard"])
def current_cycle(session: Session = Depends(get_session)) -> CycleDashboardSummary | None:
    return _journal.latest_cycle(session)


@router.get("/agents/status", response_model=list[AgentDashboardStatus], tags=["dashboard"])
def agents_status(session: Session = Depends(get_session)) -> list[AgentDashboardStatus]:
    cycle = _journal.latest_cycle(session)
    roles = {"ANNIE": "Gold Information Bot", "MIKASA": "Market Analyst Bot", "EREN": "Trading Bot", "COMMANDER_ERWIN": "Deterministic Master Risk Controller", "ARMIN": "Performance Review Bot", "CPT_LEVI": "OpenAI-powered AI Review and Strategy Research Bot"}
    if cycle is None: return [AgentDashboardStatus(name=name, role=role, state="UNKNOWN") for name, role in roles.items()]
    events = _journal.timeline(session, cycle.correlation_id); latest = {event.agent_name: event for event in events}
    return [AgentDashboardStatus(name=name, role=role, state=latest[name].event_type if name in latest else "NOT_REACHED", correlation_id=cycle.correlation_id, last_run_at=latest[name].created_at if name in latest else cycle.completed_at, latest_output=latest[name].payload if name in latest else None) for name, role in roles.items()]


@router.get("/journal", response_model=JournalPage, tags=["dashboard"])
def journal_page(offset: int = 0, limit: int = 50, agent: str | None = None, correlation_id: str | None = None, session: Session = Depends(get_session)) -> JournalPage:
    from uuid import UUID
    parsed = UUID(correlation_id) if correlation_id else None
    return _journal.journal_page(session, offset, limit, agent, parsed)


@router.get("/replay/{correlation_id}", response_model=list[DecisionTimelineEvent], tags=["dashboard"])
def replay(correlation_id: str, session: Session = Depends(get_session)) -> list[DecisionTimelineEvent]:
    return decision_timeline(correlation_id, session)


@router.get("/learning", response_model=LearningDashboardResponse, tags=["dashboard"])
def learning_dashboard(session: Session = Depends(get_session)) -> LearningDashboardResponse:
    """Return read-only Armin metrics from persisted closed trades.

    Promotion is intentionally never performed by this endpoint; it only exposes
    evidence for a human review and leaves strategy configuration untouched.
    """
    persistence_warning: str | None = None
    try:
        records = tuple(session.scalars(select(ClosedTradeRecord).order_by(ClosedTradeRecord.closed_at)).all())
    except SQLAlchemyError as exc:
        # Learning is unavailable until migrations exist; returning an explicit
        # insufficient-data state is safer than a 500 or fabricated metrics.
        records = ()
        persistence_warning = f"Closed-trade history unavailable until database migrations are applied ({type(exc).__name__})"
    grouped: dict[str, list[TradeOutcome]] = defaultdict(list)
    for record in records:
        grouped[record.strategy_version].append(
            TradeOutcome(
                strategy_version=record.strategy_version,
                session=record.session,
                pnl=Decimal(str(record.pnl)),
                reward_risk=Decimal(str(record.reward_risk)),
            )
        )
    rankings: list[StrategyRanking] = []
    for version, trades in grouped.items():
        report = _armin.analyze(tuple(trades))
        wins = sum(1 for trade in trades if trade.pnl > 0)
        net_pnl = sum((trade.pnl for trade in trades), Decimal("0"))
        average_rr = sum((trade.reward_risk for trade in trades), Decimal("0")) / len(trades)
        rankings.append(
            StrategyRanking(
                strategy_name=version.split("@", 1)[0],
                version=version,
                status="OBSERVED",
                trade_count=report.trade_count,
                win_rate=wins / report.trade_count if report.trade_count else None,
                profit_factor=float(report.profit_factor) if report.profit_factor is not None else None,
                average_reward_risk=float(average_rr),
                net_return=float(net_pnl),
                maximum_drawdown=float(report.maximum_drawdown),
                promotion_status="NOT_PROMOTED",
            )
        )
    rankings.sort(key=lambda item: item.net_return or 0, reverse=True)
    paper_records: tuple[SimulatedPositionRecord, ...]
    try:
        paper_records = tuple(session.scalars(select(SimulatedPositionRecord).where(SimulatedPositionRecord.status == "CLOSED").order_by(SimulatedPositionRecord.closed_at)).all())
    except SQLAlchemyError:
        paper_records = ()
    paper_grouped: dict[str, list[TradeOutcome]] = defaultdict(list)
    for record in paper_records:
        risk = abs(Decimal(str(record.entry_price)) - Decimal(str(record.stop_loss)))
        reward = abs(Decimal(str(record.take_profit)) - Decimal(str(record.entry_price)))
        paper_grouped[record.strategy_version].append(TradeOutcome(
            strategy_version=record.strategy_version, session="PAPER",
            pnl=Decimal(str(record.pnl or 0)), reward_risk=reward / risk if risk else Decimal("0"),
        ))
    paper_rankings: list[StrategyRanking] = []
    for version, trades in paper_grouped.items():
        report = _armin.analyze(tuple(trades)); wins = sum(1 for trade in trades if trade.pnl > 0)
        net_pnl = sum((trade.pnl for trade in trades), Decimal("0"))
        average_rr = sum((trade.reward_risk for trade in trades), Decimal("0")) / len(trades)
        paper_rankings.append(StrategyRanking(
            strategy_name=version.split("@", 1)[0], version=version, status="PAPER_OBSERVED",
            trade_count=report.trade_count, win_rate=wins / report.trade_count if report.trade_count else None,
            profit_factor=float(report.profit_factor) if report.profit_factor is not None else None,
            average_reward_risk=float(average_rr), net_return=float(net_pnl),
            maximum_drawdown=float(report.maximum_drawdown), promotion_status="PAPER_ONLY_NOT_PROMOTED",
        ))
    paper_rankings.sort(key=lambda item: item.net_return or 0, reverse=True)
    insufficient = len(records) < 30
    warnings = tuple(filter(None, (
        "No statistically sufficient closed-trade sample is available" if insufficient else None,
        persistence_warning,
    )))
    recommendations = tuple(filter(None, (
        "Collect at least 30 broker closed trades before considering any live promotion" if insufficient else None,
        "Collect at least 30 forward paper trades before considering demo promotion" if len(paper_records) < 30 else None,
    )))
    lessons = tuple(note for version in grouped for note in _armin.analyze(tuple(grouped[version])).learning_notes)
    return LearningDashboardResponse(
        lessons=lessons,
        recommendations=recommendations,
        warnings=warnings,
        insufficient_data=insufficient,
        strategies=tuple(rankings),
        paper_strategies=tuple(paper_rankings),
    )


@router.get("/strategies", response_model=tuple[StrategyRanking, ...], tags=["dashboard"])
def strategy_rankings(session: Session = Depends(get_session)) -> tuple[StrategyRanking, ...]:
    return learning_dashboard(session).strategies


@router.get("/strategies/catalog", response_model=tuple[StrategySpec, ...], tags=["strategies"])
def strategy_catalog() -> tuple[StrategySpec, ...]:
    """Return research candidates; presence here never grants execution authority."""
    return CATALOG


@router.get("/strategies/coverage", tags=["strategies", "dashboard"])
def strategy_coverage(session: Session = Depends(get_session)) -> dict[str, object]:
    """Show core situation quotas and the independent replacement reserve.

    This endpoint is advisory only.  Coverage never authorizes an order or
    promotes a strategy; it exposes whether the research/shadow library has
    enough candidates to keep the collective operating after degradation.
    """
    plan = build_coverage_plan(CATALOG)
    rows = session.scalars(select(StrategyRecord)).all()
    registered = {row.version: row.status for row in rows}
    return coverage_status(plan, registered)


@router.get("/strategies/validation", response_model=list[dict[str, object]], tags=["strategies"])
def strategy_validation_results(session: Session = Depends(get_session)) -> list[dict[str, object]]:
    rows = session.scalars(select(ExperimentRecord).where(ExperimentRecord.name.like("catalog-validation:%"))).all()
    results = [json.loads(row.proposal_json) for row in rows]
    return sorted(results, key=lambda item: int(item.get("rank", 999999)))


@router.get("/strategies/shadow-status", response_model=list[dict[str, object]], tags=["strategies"])
def strategy_shadow_status(session: Session = Depends(get_session)) -> list[dict[str, object]]:
    strategies = session.scalars(select(StrategyRecord).where(StrategyRecord.status.in_(("SHADOW_CANDIDATE", "SHADOW", "DEMO_CANDIDATE")))).all()
    observations = session.scalars(select(ExperimentRecord).where(ExperimentRecord.name.like("shadow-observation:%"))).all()
    output = []
    for strategy in strategies:
        payloads = [json.loads(row.proposal_json) for row in observations if row.name.startswith(f"shadow-observation:{strategy.version}:")]
        actionable = [item for item in payloads if item.get("signal") in ("BUY", "SELL")]
        outcomes = [Decimal(item["outcome_pnl"]) for item in actionable if "outcome_pnl" in item]
        gains = sum((value for value in outcomes if value > 0), Decimal("0")); losses = abs(sum((value for value in outcomes if value < 0), Decimal("0")))
        expectancy = sum(outcomes, Decimal("0")) / len(outcomes) if outcomes else None
        profit_factor = gains / losses if losses else None
        ready = len(payloads) >= 50 and len(outcomes) >= 10 and expectancy is not None and expectancy > 0 and (profit_factor is None or profit_factor >= Decimal("1.10"))
        output.append({"version": strategy.version, "status": strategy.status, "observations": len(payloads), "actionable_signals": len(actionable), "completed_outcomes": len(outcomes), "expectancy": float(expectancy) if expectancy is not None else None, "profit_factor": float(profit_factor) if profit_factor is not None else None, "demo_candidate_ready": ready})
    return output


@router.get("/strategies/registry", response_model=tuple[StrategyRegistryItem, ...], tags=["strategies"])
def strategy_registry(session: Session = Depends(get_session)) -> tuple[StrategyRegistryItem, ...]:
    rows = session.scalars(select(StrategyRecord).order_by(StrategyRecord.created_at.desc())).all()
    return tuple(StrategyRegistryItem(name=row.name, version=row.version, status=row.status, config=json.loads(row.config_json), promotion_notes=row.promotion_notes, created_at=row.created_at, promoted_at=row.promoted_at) for row in rows)


@router.post("/strategies", response_model=StrategyRegistryItem, tags=["strategies"])
def register_strategy(request: StrategyRegistrationRequest, session: Session = Depends(get_session), _: Role = Depends(require_role(Role.OPERATOR))) -> StrategyRegistryItem:
    if session.scalar(select(StrategyRecord).where(StrategyRecord.version == request.version)):
        raise HTTPException(status_code=409, detail="Strategy version already exists")
    row = StrategyRecord(name=request.name, version=request.version, status="DRAFT", config_json=json.dumps(request.config))
    session.add(row)
    session.commit()
    session.refresh(row)
    return StrategyRegistryItem(name=row.name, version=row.version, status=row.status, config=request.config, promotion_notes=row.promotion_notes, created_at=row.created_at, promoted_at=row.promoted_at)


@router.post("/strategies/{version}/promote", response_model=StrategyRegistryItem, tags=["strategies"])
def promote_strategy(version: str, request: StrategyPromotionRequest, session: Session = Depends(get_session), _: Role = Depends(require_role(Role.ADMIN))) -> StrategyRegistryItem:
    row = session.scalar(select(StrategyRecord).where(StrategyRecord.version == version))
    if row is None:
        raise HTTPException(status_code=404, detail="Strategy version not found")
    if (session.scalar(select(func.count()).select_from(ClosedTradeRecord)) or 0) < 30:
        raise HTTPException(status_code=409, detail="At least 30 closed trades are required before promotion")
    for active in session.scalars(select(StrategyRecord).where(StrategyRecord.status == "ACTIVE")).all():
        active.status = "RETIRED"
    row.status = "ACTIVE"
    row.promotion_notes = request.notes
    row.promoted_at = datetime.now(UTC)
    session.commit()
    return StrategyRegistryItem(name=row.name, version=row.version, status=row.status, config=json.loads(row.config_json), promotion_notes=row.promotion_notes, created_at=row.created_at, promoted_at=row.promoted_at)


@router.get("/levi/proposals", response_model=list[dict[str, object]], tags=["levi"])
def levi_proposals(session: Session = Depends(get_session)) -> list[dict[str, object]]:
    rows = session.scalars(select(ResearchProposalRecord).order_by(ResearchProposalRecord.created_at.desc())).all()
    return [{"id": str(row.id), "title": row.title, "summary": row.summary, "citations": json.loads(row.citations_json), "status": row.status, "created_at": row.created_at} for row in rows]


@router.post("/levi/review", response_model=LeviReview, tags=["levi"])
def levi_review(request: LeviReviewRequest, session: Session = Depends(get_session), _: Role = Depends(require_role(Role.OPERATOR))) -> LeviReview:
    settings = get_settings()
    review = LeviService(settings.openai_model, settings.openai_api_key).review(request.journal_context)
    for experiment in review.experiments:
        session.add(ResearchProposalRecord(title=experiment[:255], summary=review.summary, citations_json=json.dumps(review.citations), status="PROPOSED"))
    session.commit()
    return review


@router.get("/experiments", response_model=list[dict[str, object]], tags=["armin"])
def experiments(session: Session = Depends(get_session)) -> list[dict[str, object]]:
    rows = session.scalars(select(ExperimentRecord).order_by(ExperimentRecord.created_at.desc())).all()
    return [{"id": str(row.id), "name": row.name, "status": row.status, "proposal": json.loads(row.proposal_json), "created_at": row.created_at} for row in rows]


@router.post("/experiments", response_model=dict[str, object], tags=["armin"])
def create_experiment(request: ExperimentRequest, session: Session = Depends(get_session), _: Role = Depends(require_role(Role.OPERATOR))) -> dict[str, object]:
    row = ExperimentRecord(name=request.name, status="PROPOSED", proposal_json=json.dumps(request.proposal))
    session.add(row)
    session.commit()
    session.refresh(row)
    return {"id": str(row.id), "name": row.name, "status": row.status, "proposal": request.proposal, "created_at": row.created_at}


@router.post("/experiments/{experiment_id}/status", response_model=dict[str, object], tags=["armin"])
def update_experiment_status(experiment_id: str, request: ExperimentStatusRequest, session: Session = Depends(get_session), _: Role = Depends(require_role(Role.OPERATOR))) -> dict[str, object]:
    from uuid import UUID
    row = session.get(ExperimentRecord, UUID(experiment_id))
    if row is None:
        raise HTTPException(status_code=404, detail="Experiment not found")
    row.status = request.status
    session.commit()
    return {"id": str(row.id), "name": row.name, "status": row.status, "proposal": json.loads(row.proposal_json), "created_at": row.created_at}


@router.get("/ops/alerts", response_model=list[dict[str, object]], tags=["operations"])
def operational_alerts(session: Session = Depends(get_session)) -> list[dict[str, object]]:
    rows = session.scalars(select(AlertRecord).where(AlertRecord.resolved_at.is_(None)).order_by(AlertRecord.created_at.desc())).all()
    return [{"id": str(row.id), "severity": row.severity, "message": row.message, "created_at": row.created_at} for row in rows]


@router.get("/ops/execution-incidents", response_model=list[dict[str, object]], tags=["operations"])
def execution_incidents(session: Session = Depends(get_session)) -> list[dict[str, object]]:
    return [
        {
            "id": str(row.id),
            "incident_type": row.incident_type,
            "severity": row.severity,
            "position_ticket": row.position_ticket,
            "correlation_id": str(row.correlation_id) if row.correlation_id else None,
            "message": row.message,
            "created_at": row.created_at,
            "resolved_at": row.resolved_at,
        }
        for row in _journal.unresolved_execution_incidents(session)
    ]


@router.post("/ops/execution-incidents/{incident_id}/resolve", response_model=dict[str, object], tags=["operations"])
def resolve_execution_incident(
    incident_id: str,
    request: IncidentResolveRequest,
    session: Session = Depends(get_session),
    _: Role = Depends(require_role(Role.OPERATOR)),
) -> dict[str, object]:
    from uuid import UUID
    row = session.get(ExecutionIncidentRecord, UUID(incident_id))
    if row is None:
        raise HTTPException(status_code=404, detail="Execution incident not found")
    row.resolved_at = datetime.now(UTC)
    row.resolved_by = request.resolved_by
    row.resolution_note = request.resolution_note
    session.commit()
    return {"id": str(row.id), "resolved_at": row.resolved_at, "status": "RESOLVED"}


@router.post("/ops/alerts", response_model=dict[str, object], tags=["operations"])
def create_alert(request: AlertRequest, session: Session = Depends(get_session), _: Role = Depends(require_role(Role.OPERATOR))) -> dict[str, object]:
    row = AlertRecord(severity=request.severity, message=request.message)
    session.add(row)
    session.commit()
    session.refresh(row)
    return {"id": str(row.id), "severity": row.severity, "message": row.message, "created_at": row.created_at}


@router.post("/ops/alerts/{alert_id}/resolve", response_model=dict[str, object], tags=["operations"])
def resolve_alert(alert_id: str, session: Session = Depends(get_session), _: Role = Depends(require_role(Role.OPERATOR))) -> dict[str, object]:
    from uuid import UUID
    row = session.get(AlertRecord, UUID(alert_id))
    if row is None:
        raise HTTPException(status_code=404, detail="Alert not found")
    row.resolved_at = datetime.now(UTC)
    session.commit()
    return {"id": str(row.id), "resolved_at": row.resolved_at, "status": "RESOLVED"}


@router.get("/annie/news-report", response_model=AnnieNewsReport, tags=["annie"])
def annie_news_report() -> AnnieNewsReport:
    """Fetch source-linked headlines for human review; never creates a trade signal."""
    return _annie.assess_headlines(GoogleNewsRssSearch().search_gold_news())


@router.post("/risk/assess", response_model=RiskDecision, tags=["commander-erwin"])
def assess_risk(
    proposal: TradeProposal,
    account: AccountSnapshot,
    profile: RiskProfile,
    current_spread: Decimal,
    session: Session = Depends(get_session),
    _: Role = Depends(require_role(Role.OPERATOR)),
) -> RiskDecision:
    """Evaluate a proposal without sending an order to MT5, then journal it."""
    try:
        decision = _erwin.evaluate(proposal, account, profile, current_spread, execution_locked=_journal.has_critical_execution_incident(session))
        _journal.record_assessment(session, proposal, decision)
        return decision
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/simulation/decision-preview", response_model=DecisionPreview, tags=["simulation"])
async def decision_preview(request: DecisionPreviewRequest, session: Session = Depends(get_session), _: Role = Depends(require_role(Role.OPERATOR))) -> DecisionPreview:
    """Run, journal, and return the agent chain; it cannot execute an order."""
    preview = _preview_workflow.run(
        market=request.market,
        events=request.events,
        source_freshness_minutes=request.source_freshness_minutes,
        account=request.account,
        profile=request.profile,
    )
    _journal.record_preview(session, preview)
    await mission_events.publish({"type": "decision_completed", "correlation_id": str(preview.correlation_id), "final_message": preview.final_message})
    return preview


@router.get(
    "/journal/timeline/{correlation_id}",
    response_model=list[DecisionTimelineEvent],
    tags=["trade-journal"],
)
def decision_timeline(correlation_id: str, session: Session = Depends(get_session)) -> list[DecisionTimelineEvent]:
    """Return the ordered, immutable agent timeline for one decision path."""
    from uuid import UUID

    try:
        parsed_id = UUID(correlation_id)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="correlation_id must be a UUID") from exc
    events = _journal.timeline(session, parsed_id)
    if not events:
        raise HTTPException(status_code=404, detail="Decision timeline not found")
    return events


@router.websocket("/ws/mission-control")
async def mission_control_stream(websocket: WebSocket) -> None:
    """Read-only live fan-out for dashboard status and completed decisions."""
    await websocket.accept()
    try:
        stream = mission_events.subscribe()
        while True:
            try: event = await asyncio.wait_for(anext(stream), timeout=15)
            except StopAsyncIteration:
                break
            except TimeoutError:
                settings = get_settings()
                event = {
                    "type": "system_status",
                    "execution": "enabled" if settings.execution_enabled else "disabled",
                    "kill_switch_active": settings.kill_switch_active,
                    "emitted_at": datetime.now(UTC).isoformat(),
                }
            await websocket.send_json(event)
    except WebSocketDisconnect:
        return
