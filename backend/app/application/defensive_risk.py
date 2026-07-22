"""Deterministic, persistent, demo-only defensive position sizing."""

from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal, ROUND_DOWN
from enum import StrEnum

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config.settings import Settings, get_settings
from app.domain.trading.models import AccountSnapshot, SymbolSpecification
from app.infrastructure.persistence.models import ClosedTradeRecord, DefensiveRiskStateRecord


class RiskState(StrEnum):
    NORMAL = "NORMAL"
    CAUTION = "CAUTION"
    DEFENSIVE = "DEFENSIVE"
    HALTED = "HALTED"
    UNKNOWN = "RISK_STATE_UNKNOWN"


class RiskSizingMode(StrEnum):
    OFF = "OFF"
    SHADOW = "SHADOW"
    DEMO_ACTIVE = "DEMO_ACTIVE"


SEVERITY = {
    RiskState.NORMAL: 0,
    RiskState.CAUTION: 1,
    RiskState.DEFENSIVE: 2,
    RiskState.HALTED: 3,
    RiskState.UNKNOWN: 3,
}


class DefensiveRiskUnavailable(RuntimeError):
    """State could not be determined; callers must block new risk."""


class DefensiveVolumeBlocked(RuntimeError):
    """A new order cannot receive a defensively safe volume."""


@dataclass(frozen=True)
class RiskStateAssessment:
    state: RiskState
    risk_multiplier: Decimal
    consecutive_losses: int
    hard_stop_count: int
    consecutive_hard_stops: int
    session_start_balance: Decimal
    current_balance: Decimal
    session_realized_pnl: Decimal
    session_drawdown_usd: Decimal
    session_drawdown_pct: Decimal
    peak_session_equity: Decimal
    current_equity: Decimal
    equity_drawdown_usd: Decimal
    equity_drawdown_pct: Decimal
    recent_average_loss: Decimal | None
    recent_average_win: Decimal | None
    recent_profit_factor: Decimal | None
    state_reason: str
    state_entered_at: datetime
    last_updated_at: datetime
    cooldown_until: datetime | None
    recovery_wins: int

    @property
    def new_entries_blocked(self) -> bool:
        return self.state in {RiskState.HALTED, RiskState.UNKNOWN} or (
            self.cooldown_until is not None and self.cooldown_until > datetime.now(UTC)
        )


@dataclass(frozen=True)
class DefensiveVolumeDecision:
    mode: RiskSizingMode
    state: RiskState
    normal_volume: Decimal
    candidate_volume: Decimal
    risk_multiplier: Decimal
    calculated_volume: Decimal
    adaptive_recommended_volume: Decimal | None
    approved_volume: Decimal | None
    broker_minimum: Decimal
    broker_maximum: Decimal
    broker_step: Decimal
    broker_volume_limit: Decimal | None
    skipped: bool
    reason: str


def configured_normal_volume(settings: Settings | None = None) -> Decimal:
    settings = settings or get_settings()
    return Decimal(str(settings.risk_normal_volume or settings.avenger_volume))


def risk_multiplier_for(state: RiskState, settings: Settings | None = None) -> Decimal:
    settings = settings or get_settings()
    values = {
        RiskState.NORMAL: settings.risk_normal_multiplier,
        RiskState.CAUTION: settings.risk_caution_multiplier,
        RiskState.DEFENSIVE: settings.risk_defensive_multiplier,
        RiskState.HALTED: settings.risk_halted_multiplier,
        RiskState.UNKNOWN: settings.risk_halted_multiplier,
    }
    return Decimal(str(values[state]))


def _floor_to_step(value: Decimal, step: Decimal) -> Decimal:
    if value <= 0:
        return Decimal("0")
    return (value / step).to_integral_value(rounding=ROUND_DOWN) * step


def calculate_allowed_volume(
    normal_volume: Decimal,
    candidate_volume: Decimal,
    assessment: RiskStateAssessment,
    specification: SymbolSpecification,
    mode: RiskSizingMode | str,
    allow_cooldown_override: bool = False,
) -> DefensiveVolumeDecision:
    """Authorize a new volume without ever rounding defensive risk upward."""
    mode = RiskSizingMode(mode)
    if normal_volume <= 0 or candidate_volume <= 0:
        raise DefensiveVolumeBlocked("Configured and candidate volumes must be positive")
    if candidate_volume > normal_volume:
        raise DefensiveVolumeBlocked(
            f"Requested volume {candidate_volume} exceeds configured normal ceiling {normal_volume}"
        )
    broker_cap = min(specification.volume_max, specification.volume_limit or specification.volume_max)
    normal_ceiling = min(normal_volume, broker_cap)
    baseline = min(candidate_volume, normal_ceiling)
    multiplier = Decimal("1") if mode is RiskSizingMode.OFF else assessment.risk_multiplier
    calculated = baseline * multiplier
    adaptive = _floor_to_step(calculated, specification.volume_step)
    actual = _floor_to_step(baseline, specification.volume_step)

    if mode is not RiskSizingMode.OFF and assessment.new_entries_blocked:
        cooldown_only = assessment.state not in {RiskState.HALTED, RiskState.UNKNOWN} and assessment.cooldown_until is not None
        if not (allow_cooldown_override and cooldown_only):
            raise DefensiveVolumeBlocked(
                f"New entries blocked by defensive state {assessment.state}: {assessment.state_reason}"
            )
    if mode is RiskSizingMode.DEMO_ACTIVE:
        if adaptive < specification.volume_min:
            raise DefensiveVolumeBlocked(
                "DEFENSIVE_VOLUME_BELOW_BROKER_MINIMUM: calculated volume cannot be rounded upward"
            )
        actual = adaptive
    elif actual < specification.volume_min:
        raise DefensiveVolumeBlocked("Baseline volume is below the broker minimum")

    if actual > normal_volume:
        raise DefensiveVolumeBlocked("Approved volume exceeded configured normal volume ceiling")
    return DefensiveVolumeDecision(
        mode=mode,
        state=assessment.state,
        normal_volume=normal_volume,
        candidate_volume=candidate_volume,
        risk_multiplier=multiplier,
        calculated_volume=calculated,
        adaptive_recommended_volume=adaptive if mode is not RiskSizingMode.OFF else None,
        approved_volume=actual,
        broker_minimum=specification.volume_min,
        broker_maximum=specification.volume_max,
        broker_step=specification.volume_step,
        broker_volume_limit=specification.volume_limit,
        skipped=False,
        reason=(
            "Adaptive sizing is OFF; baseline volume retained"
            if mode is RiskSizingMode.OFF
            else (
                f"{assessment.state} risk state applied at {multiplier}x"
                + ("; DEMO defensive cooldown override active" if allow_cooldown_override and assessment.new_entries_blocked else "")
            )
        ),
    )


def _session_key(now: datetime, reset_hour: int) -> str:
    anchor = now.replace(hour=reset_hour, minute=0, second=0, microsecond=0)
    if now < anchor:
        anchor -= timedelta(days=1)
    return anchor.date().isoformat()


def _is_hard_stop(row: ClosedTradeRecord) -> bool:
    reason = str(row.exit_reason or "").upper()
    return any(marker in reason for marker in ("STOP", "HARD_STOP", "PROTECTION_FAILED", "MISSING_BROKER_PROTECTION"))


def _as_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value if value.tzinfo else value.replace(tzinfo=UTC)


class DefensiveRiskEngine:
    """State machine with explicit severity, persistence, and gradual recovery."""

    state_id = 1

    def refresh(
        self,
        session: Session,
        account: AccountSnapshot,
        execution_locked: bool = False,
        now: datetime | None = None,
        settings: Settings | None = None,
    ) -> RiskStateAssessment:
        now = now or datetime.now(UTC)
        settings = settings or get_settings()
        balance = Decimal(str(account.balance or account.equity))
        equity = Decimal(str(account.equity))
        if balance <= 0 or equity <= 0:
            raise DefensiveRiskUnavailable("Account balance/equity is unavailable or non-positive")
        row = session.get(DefensiveRiskStateRecord, self.state_id)
        key = _session_key(now, settings.risk_session_reset_hour_utc)
        if row is None:
            row = DefensiveRiskStateRecord(
                id=self.state_id,
                session_key=key,
                current_risk_state=RiskState.NORMAL.value,
                risk_multiplier=float(risk_multiplier_for(RiskState.NORMAL, settings)),
                session_start_balance=balance,
                current_balance=balance,
                peak_session_equity=equity,
                current_equity=equity,
                state_reason="Initial defensive risk state",
                state_entered_at=now,
                last_updated_at=now,
                session_started_at=now,
            )
            session.add(row)
            session.flush()
        elif row.session_key != key and settings.risk_auto_reset_session_boundary:
            row.session_key = key
            row.session_started_at = now
            row.session_start_balance = balance
            row.current_risk_state = RiskState.NORMAL.value
            row.state_reason = "Configured defensive risk session boundary reset"
            row.state_entered_at = now
            row.consecutive_losses = 0
            row.hard_stop_count = 0
            row.consecutive_hard_stops = 0
            row.recovery_wins = 0
            row.cooldown_until = None
            row.peak_session_equity = equity

        started_at = _as_utc(row.session_started_at) or now
        trades = list(
            session.scalars(
                select(ClosedTradeRecord)
                .where(ClosedTradeRecord.closed_at >= started_at)
                .order_by(ClosedTradeRecord.closed_at.desc())
            ).all()
        )
        pnl_values = [Decimal(str(trade.pnl)) for trade in trades]
        consecutive_losses = 0
        for pnl in pnl_values:
            if pnl < 0:
                consecutive_losses += 1
            else:
                break
        hard_stops = sum(1 for trade in trades if _is_hard_stop(trade))
        consecutive_hard_stops = 0
        for trade in trades:
            if _is_hard_stop(trade) and Decimal(str(trade.pnl)) < 0:
                consecutive_hard_stops += 1
            else:
                break
        session_pnl = sum(pnl_values, Decimal("0"))
        session_drawdown_usd = max(Decimal("0"), -session_pnl)
        session_drawdown_pct = (session_drawdown_usd / row.session_start_balance * Decimal("100")) if row.session_start_balance else Decimal("100")
        peak_equity = max(Decimal(str(row.peak_session_equity)), equity)
        equity_drawdown_usd = max(Decimal("0"), peak_equity - equity)
        equity_drawdown_pct = (equity_drawdown_usd / peak_equity * Decimal("100")) if peak_equity else Decimal("100")
        recent = trades[: settings.risk_recent_trade_count]
        wins = [value for value in (Decimal(str(trade.pnl)) for trade in recent) if value > 0]
        losses = [abs(value) for value in (Decimal(str(trade.pnl)) for trade in recent) if value < 0]
        average_win = sum(wins, Decimal("0")) / Decimal(len(wins)) if wins else None
        average_loss = sum(losses, Decimal("0")) / Decimal(len(losses)) if losses else None
        profit_factor = sum(wins, Decimal("0")) / sum(losses, Decimal("0")) if losses else None

        candidate = RiskState.NORMAL
        reasons: list[str] = []
        if execution_locked:
            candidate = RiskState.HALTED
            reasons.append("unresolved critical execution incident")
        if consecutive_losses >= settings.risk_halt_after_losses:
            candidate = max((candidate, RiskState.HALTED), key=lambda state: SEVERITY[state])
            reasons.append(f"{consecutive_losses} consecutive losses")
        elif consecutive_losses >= settings.risk_defensive_after_losses:
            candidate = max((candidate, RiskState.DEFENSIVE), key=lambda state: SEVERITY[state])
            reasons.append(f"{consecutive_losses} consecutive losses")
        elif consecutive_losses >= settings.risk_caution_after_losses:
            candidate = max((candidate, RiskState.CAUTION), key=lambda state: SEVERITY[state])
            reasons.append(f"{consecutive_losses} consecutive losses")
        if consecutive_hard_stops >= settings.risk_hard_stop_halt_after:
            candidate = max((candidate, RiskState.HALTED), key=lambda state: SEVERITY[state])
            reasons.append(f"{consecutive_hard_stops} consecutive hard stops")
        elif hard_stops >= settings.risk_hard_stop_defensive_after or consecutive_hard_stops >= settings.risk_hard_stop_defensive_after:
            candidate = max((candidate, RiskState.DEFENSIVE), key=lambda state: SEVERITY[state])
            reasons.append(f"{hard_stops} hard stops")
        elif hard_stops >= settings.risk_hard_stop_caution_after:
            candidate = max((candidate, RiskState.CAUTION), key=lambda state: SEVERITY[state])
            reasons.append(f"{hard_stops} hard stop")
        drawdown_pct = max(session_drawdown_pct, equity_drawdown_pct)
        if drawdown_pct >= settings.risk_halt_drawdown_pct:
            candidate = max((candidate, RiskState.HALTED), key=lambda state: SEVERITY[state])
            reasons.append(f"drawdown {drawdown_pct.quantize(Decimal('0.01'))}%")
        elif drawdown_pct >= settings.risk_defensive_drawdown_pct:
            candidate = max((candidate, RiskState.DEFENSIVE), key=lambda state: SEVERITY[state])
            reasons.append(f"drawdown {drawdown_pct.quantize(Decimal('0.01'))}%")
        elif drawdown_pct >= settings.risk_caution_drawdown_pct:
            candidate = max((candidate, RiskState.CAUTION), key=lambda state: SEVERITY[state])
            reasons.append(f"drawdown {drawdown_pct.quantize(Decimal('0.01'))}%")
        if len(recent) >= 3 and profit_factor is not None:
            if profit_factor < Decimal(str(settings.risk_defensive_profit_factor)):
                candidate = max((candidate, RiskState.DEFENSIVE), key=lambda state: SEVERITY[state])
                reasons.append(f"recent profit factor {profit_factor.quantize(Decimal('0.01'))}")
            elif profit_factor < Decimal(str(settings.risk_caution_profit_factor)):
                candidate = max((candidate, RiskState.CAUTION), key=lambda state: SEVERITY[state])
                reasons.append(f"recent profit factor {profit_factor.quantize(Decimal('0.01'))}")

        previous = RiskState(row.current_risk_state) if row.current_risk_state in RiskState._value2member_map_ else RiskState.UNKNOWN
        healthy_recovery_wins = 0
        for trade in trades:
            if Decimal(str(trade.pnl)) >= Decimal(str(settings.risk_min_recovery_profit_usd)):
                healthy_recovery_wins += 1
            else:
                break
        state = candidate
        if SEVERITY.get(candidate, 3) < SEVERITY.get(previous, 3) and previous not in {RiskState.NORMAL, RiskState.UNKNOWN}:
            required = (
                settings.risk_halted_recovery_wins if previous is RiskState.HALTED
                else settings.risk_recovery_wins_defensive_to_caution if previous is RiskState.DEFENSIVE
                else settings.risk_recovery_wins_caution_to_normal
            )
            target = RiskState.DEFENSIVE if previous is RiskState.HALTED else RiskState.CAUTION if previous is RiskState.DEFENSIVE else RiskState.NORMAL
            if required == 0 or healthy_recovery_wins < required:
                state = previous
                reasons.append(f"recovery requires {required or 'explicit reset'} healthy wins; have {healthy_recovery_wins}")
            else:
                state = target
                reasons.append(f"recovered after {healthy_recovery_wins} healthy wins")
        if previous is RiskState.UNKNOWN and candidate is RiskState.NORMAL:
            state = RiskState.UNKNOWN
            reasons.append("previous risk state was unknown")
        if not reasons:
            reasons.append("performance and account metrics within configured defensive limits")
        cooldown = None
        if trades and pnl_values[0] < 0 and trades[0].closed_at:
            latest_close = _as_utc(trades[0].closed_at) or now
            cooldown_seconds = settings.risk_hard_stop_cooldown_seconds if _is_hard_stop(trades[0]) else settings.risk_loss_cooldown_seconds
            if state is RiskState.DEFENSIVE:
                cooldown_seconds = max(cooldown_seconds, settings.risk_defensive_cooldown_seconds)
            candidate_cooldown = latest_close + timedelta(seconds=cooldown_seconds)
            if candidate_cooldown > now:
                cooldown = candidate_cooldown
                reasons.append(f"loss cooldown until {cooldown.isoformat()}")
        if state != previous:
            row.state_entered_at = now
        row.current_risk_state = state.value
        row.risk_multiplier = float(risk_multiplier_for(state, settings))
        row.consecutive_losses = consecutive_losses
        row.hard_stop_count = hard_stops
        row.consecutive_hard_stops = consecutive_hard_stops
        row.current_balance = balance
        row.session_realized_pnl = session_pnl
        row.session_drawdown_usd = session_drawdown_usd
        row.session_drawdown_pct = session_drawdown_pct
        row.peak_session_equity = peak_equity
        row.current_equity = equity
        row.equity_drawdown_usd = equity_drawdown_usd
        row.equity_drawdown_pct = equity_drawdown_pct
        row.recent_average_loss = average_loss
        row.recent_average_win = average_win
        row.recent_profit_factor = profit_factor
        row.recovery_wins = healthy_recovery_wins
        row.cooldown_until = cooldown
        row.state_reason = "; ".join(reasons)
        row.last_updated_at = now
        session.flush()
        return RiskStateAssessment(
            state=state,
            risk_multiplier=risk_multiplier_for(state, settings),
            consecutive_losses=consecutive_losses,
            hard_stop_count=hard_stops,
            consecutive_hard_stops=consecutive_hard_stops,
            session_start_balance=Decimal(str(row.session_start_balance)),
            current_balance=balance,
            session_realized_pnl=session_pnl,
            session_drawdown_usd=session_drawdown_usd,
            session_drawdown_pct=session_drawdown_pct,
            peak_session_equity=peak_equity,
            current_equity=equity,
            equity_drawdown_usd=equity_drawdown_usd,
            equity_drawdown_pct=equity_drawdown_pct,
            recent_average_loss=average_loss,
            recent_average_win=average_win,
            recent_profit_factor=profit_factor,
            state_reason=row.state_reason,
            state_entered_at=_as_utc(row.state_entered_at) or now,
            last_updated_at=now,
            cooldown_until=cooldown,
            recovery_wins=healthy_recovery_wins,
        )

    @staticmethod
    def read(session: Session) -> RiskStateAssessment | None:
        row = session.get(DefensiveRiskStateRecord, DefensiveRiskEngine.state_id)
        if row is None:
            return None
        state = RiskState(row.current_risk_state) if row.current_risk_state in RiskState._value2member_map_ else RiskState.UNKNOWN
        return RiskStateAssessment(
            state=state,
            risk_multiplier=Decimal(str(row.risk_multiplier)),
            consecutive_losses=row.consecutive_losses,
            hard_stop_count=row.hard_stop_count,
            consecutive_hard_stops=row.consecutive_hard_stops,
            session_start_balance=Decimal(str(row.session_start_balance)),
            current_balance=Decimal(str(row.current_balance)),
            session_realized_pnl=Decimal(str(row.session_realized_pnl)),
            session_drawdown_usd=Decimal(str(row.session_drawdown_usd)),
            session_drawdown_pct=Decimal(str(row.session_drawdown_pct)),
            peak_session_equity=Decimal(str(row.peak_session_equity)),
            current_equity=Decimal(str(row.current_equity)),
            equity_drawdown_usd=Decimal(str(row.equity_drawdown_usd)),
            equity_drawdown_pct=Decimal(str(row.equity_drawdown_pct)),
            recent_average_loss=Decimal(str(row.recent_average_loss)) if row.recent_average_loss is not None else None,
            recent_average_win=Decimal(str(row.recent_average_win)) if row.recent_average_win is not None else None,
            recent_profit_factor=Decimal(str(row.recent_profit_factor)) if row.recent_profit_factor is not None else None,
            state_reason=row.state_reason,
            state_entered_at=_as_utc(row.state_entered_at) or datetime.now(UTC),
            last_updated_at=_as_utc(row.last_updated_at) or datetime.now(UTC),
            cooldown_until=_as_utc(row.cooldown_until),
            recovery_wins=row.recovery_wins,
        )
