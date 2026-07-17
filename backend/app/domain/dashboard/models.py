from datetime import datetime
from enum import StrEnum
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class HealthState(StrEnum):
    HEALTHY = "HEALTHY"; DEGRADED = "DEGRADED"; UNAVAILABLE = "UNAVAILABLE"; DISABLED = "DISABLED"; UNKNOWN = "UNKNOWN"


class PlatformMode(StrEnum):
    READ_ONLY_SHADOW_MODE = "READ_ONLY_SHADOW_MODE"; SIMULATED_EXECUTION = "SIMULATED_EXECUTION"; DEMO_EXECUTION = "DEMO_EXECUTION"; LIVE_EXECUTION = "LIVE_EXECUTION"


class ServiceHealth(BaseModel):
    model_config = ConfigDict(frozen=True)
    state: HealthState
    message: str
    checked_at: datetime


class SystemStatusResponse(BaseModel):
    model_config = ConfigDict(frozen=True)
    platform_mode: PlatformMode
    execution_enabled: bool
    kill_switch_active: bool | None
    execution_locked: bool = False
    demo_exploration_enabled: bool = False
    mt5_terminal_trade_allowed: bool | None = None
    mt5_account_trade_allowed: bool | None = None
    mt5_account_expert_allowed: bool | None = None
    mt5: ServiceHealth
    shadow_worker: ServiceHealth
    journal: ServiceHealth
    websocket: ServiceHealth
    news: ServiceHealth
    strategy_shadow_worker: ServiceHealth
    simulation_worker: ServiceHealth
    demo_position_manager: ServiceHealth | None = None
    database: ServiceHealth
    calendar: ServiceHealth
    levi: ServiceHealth
    backtester: ServiceHealth
    disk: ServiceHealth


class AgentDashboardStatus(BaseModel):
    model_config = ConfigDict(frozen=True)
    name: str
    role: str
    state: str
    correlation_id: UUID | None = None
    last_run_at: datetime | None = None
    latest_output: dict[str, Any] | None = None


class CycleDashboardSummary(BaseModel):
    model_config = ConfigDict(frozen=True)
    correlation_id: UUID
    completed_at: datetime | None
    final_message: str | None
    event_count: int


class JournalListItem(BaseModel):
    model_config = ConfigDict(frozen=True)
    correlation_id: UUID
    sequence: int
    timestamp: datetime | None
    bot: str
    event_type: str
    payload: dict[str, Any]


class JournalPage(BaseModel):
    model_config = ConfigDict(frozen=True)
    items: tuple[JournalListItem, ...]
    offset: int = Field(ge=0)
    limit: int = Field(ge=1, le=100)
    total: int = Field(ge=0)


class StrategyRanking(BaseModel):
    model_config = ConfigDict(frozen=True)
    strategy_name: str
    version: str
    status: str
    trade_count: int
    win_rate: float | None
    profit_factor: float | None
    average_reward_risk: float | None
    net_return: float | None
    maximum_drawdown: float | None
    promotion_status: str


class StrategyRegistryItem(BaseModel):
    model_config = ConfigDict(frozen=True)
    name: str
    version: str
    status: str
    config: dict[str, Any]
    promotion_notes: str | None
    created_at: datetime | None
    promoted_at: datetime | None


class LearningDashboardResponse(BaseModel):
    model_config = ConfigDict(frozen=True)
    lessons: tuple[str, ...]
    recommendations: tuple[str, ...]
    warnings: tuple[str, ...]
    insufficient_data: bool
    strategies: tuple[StrategyRanking, ...]
    paper_strategies: tuple[StrategyRanking, ...] = ()


class AccountDashboardSnapshot(BaseModel):
    model_config = ConfigDict(frozen=True)
    account_type: str
    balance: float
    equity: float
    free_margin: float
    used_margin: float | None = None
    margin_level: float | None = None
    floating_pnl: float | None = None
    currency: str | None = None
    leverage: int | None = None
    current_exposure_pct: float = 0
    realized_daily_pnl: float = 0
    realized_weekly_pnl: float = 0
    open_position_count: int
    orders_sent: int = 0
    capital_mode: str = "SURVIVAL"
    configured_risk_per_trade_pct: float
    maximum_daily_loss_pct: float
    maximum_weekly_loss_pct: float
    execution_permission: str


class SymbolDashboardSnapshot(BaseModel):
    model_config = ConfigDict(frozen=True)
    symbol: str
    bid: float | None
    ask: float | None
    spread: float | None
    tick_time_msc: int | None


class PositionDashboardItem(BaseModel):
    model_config = ConfigDict(frozen=True)
    ticket: str
    symbol: str
    side: str
    volume: float
    price_open: float
    stop_loss: float | None
    take_profit: float | None
    profit: float
    opened_at: datetime | None
    estimated_net_profit: float | None = None
    initial_risk_usd: float | None = None
    current_r: float | None = None
    peak_profit: float | None = None
    peak_r: float | None = None
    active_exit_policy: str | None = None
    profit_management_state: str | None = None
    breakeven_level: float | None = None
    locked_profit_floor: float | None = None
    trailing_floor: float | None = None
    allowed_giveback: float | None = None
    last_sl_modified_at: datetime | None = None
    close_attempt_count: int = 0
    pending_exit_reason: str | None = None
    latest_mt5_error: str | None = None
    execution_locked: bool = False


class SimulatedPositionDashboardItem(BaseModel):
    model_config = ConfigDict(frozen=True)
    id: UUID
    correlation_id: UUID
    strategy_version: str
    symbol: str
    side: str
    volume: float
    entry_price: float
    stop_loss: float
    take_profit: float
    exit_price: float | None
    pnl: float | None
    status: str
    close_reason: str | None
    opened_at: datetime
    closed_at: datetime | None


class FillDashboardItem(BaseModel):
    model_config = ConfigDict(frozen=True)
    deal_ticket: str
    order_ticket: str | None
    symbol: str
    side: str
    volume: float
    price: float
    profit: float
    filled_at: datetime


class ClosedTradeDashboardItem(BaseModel):
    model_config = ConfigDict(frozen=True)
    strategy_version: str
    session: str
    pnl: float
    reward_risk: float
    source_deal_ticket: str | None
    closed_at: datetime | None


class BrokerClosedPositionDashboardItem(BaseModel):
    model_config = ConfigDict(frozen=True)
    position_id: str
    symbol: str
    side: str
    volume: float
    entry_price: float
    exit_price: float
    pnl: float
    opened_at: datetime
    closed_at: datetime
    entry_deal_ticket: str
    exit_deal_ticket: str
    close_order_ticket: str | None


class ChartBar(BaseModel):
    model_config = ConfigDict(frozen=True)
    timestamp: datetime
    open: float
    high: float
    low: float
    close: float


class ChartResponse(BaseModel):
    model_config = ConfigDict(frozen=True)
    symbol: str
    bars: tuple[ChartBar, ...]
    markers: tuple["ChartMarker", ...] = ()


class ChartMarker(BaseModel):
    model_config = ConfigDict(frozen=True)
    timestamp: datetime | None
    label: str
    marker_type: str
    correlation_id: UUID
    sequence: int


ChartResponse.model_rebuild()
