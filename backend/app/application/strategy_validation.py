"""Cost-aware, chronological validation for research-only strategy candidates."""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from hashlib import sha256
from math import sqrt
from statistics import fmean, pstdev

from pydantic import BaseModel, ConfigDict

from app.infrastructure.mt5.gateway import Mt5Bar
from app.strategies.catalog import StrategySpec
from app.strategies.validation_policy import LOCKED_POLICY


class CostModel(BaseModel):
    model_config = ConfigDict(frozen=True)
    spread: Decimal = Decimal("0.30")
    slippage: Decimal = Decimal("0.10")


class WindowMetrics(BaseModel):
    model_config = ConfigDict(frozen=True)
    name: str
    bars: int
    trades: int
    net_pnl: Decimal
    gross_profit: Decimal
    gross_loss: Decimal
    win_rate: Decimal | None
    profit_factor: Decimal | None
    expectancy: Decimal | None
    maximum_drawdown: Decimal


class CandidateValidation(BaseModel):
    model_config = ConfigDict(frozen=True)
    version: str
    family: str
    signal_fingerprint: str
    in_sample: WindowMetrics
    out_of_sample: tuple[WindowMetrics, ...]
    oos_net_pnl: Decimal
    oos_profit_factor: Decimal | None
    oos_expectancy: Decimal | None
    oos_maximum_drawdown: Decimal
    positive_oos_windows: int
    robustness_score: Decimal
    stable: bool
    duplicate_of: str | None = None
    rejection_reasons: tuple[str, ...] = ()
    rank: int | None = None


@dataclass(frozen=True)
class _Trade:
    pnl: Decimal


def _ema(values: list[float], period: int) -> float:
    alpha = 2.0 / (period + 1)
    result = values[0]
    for value in values[1:]:
        result += alpha * (value - result)
    return result


def _rsi(values: list[float], period: int) -> float:
    moves = [values[i] - values[i - 1] for i in range(len(values) - period, len(values))]
    gains = sum(max(move, 0) for move in moves) / period
    losses = sum(max(-move, 0) for move in moves) / period
    return 100.0 if losses == 0 else 100.0 - 100.0 / (1.0 + gains / losses)


def _signal(spec: StrategySpec, bars: tuple[Mt5Bar, ...], index: int) -> int:
    p = spec.parameters
    closes = [float(bar.close) for bar in bars[max(0, index - 219): index + 1]]
    if spec.family == "EMA_CROSS":
        slow = int(p["slow"])
        if len(closes) < slow: return 0
        return 1 if _ema(closes[-slow:], int(p["fast"])) > _ema(closes[-slow:], slow) else -1
    if spec.family == "DONCHIAN_BREAKOUT":
        lookback = int(p["entry_lookback"])
        if index < lookback: return 0
        prior = bars[index - lookback:index]
        if bars[index].close > max(bar.high for bar in prior): return 1
        if bars[index].close < min(bar.low for bar in prior): return -1
        return 0
    if spec.family == "RSI_REVERSION":
        period = int(p["period"])
        if len(closes) <= period: return 0
        value = _rsi(closes, period)
        return 1 if value <= float(p["lower"]) else -1 if value >= float(p["upper"]) else 0
    if spec.family == "BOLLINGER_REVERSION":
        period = int(p["period"])
        if len(closes) < period: return 0
        window = closes[-period:]; mean = fmean(window); deviation = pstdev(window) * float(p["deviation"])
        return 1 if closes[-1] < mean - deviation else -1 if closes[-1] > mean + deviation else 0
    if spec.family == "MACD_MOMENTUM":
        slow = int(p["slow"]); signal_period = int(p["signal"])
        if len(closes) < slow + signal_period: return 0
        macd_values = []
        for end in range(len(closes) - signal_period + 1, len(closes) + 1):
            sample = closes[:end]
            macd_values.append(_ema(sample[-slow:], int(p["fast"])) - _ema(sample[-slow:], slow))
        macd = macd_values[-1]; signal = _ema(macd_values, signal_period)
        return 1 if macd > signal else -1 if macd < signal else 0
    if spec.family == "SMA_CROSS":
        slow = int(p["slow"])
        if len(closes) < slow: return 0
        fast = int(p["fast"])
        return 1 if fmean(closes[-fast:]) > fmean(closes[-slow:]) else -1
    if spec.family == "ROC_MOMENTUM":
        period = int(p["period"])
        if len(closes) <= period: return 0
        roc = 100.0 * (closes[-1] / closes[-period - 1] - 1.0)
        threshold = float(p["threshold"])
        return 1 if roc >= threshold else -1 if roc <= -threshold else 0
    if spec.family in ("CCI_REVERSION", "KELTNER_BREAKOUT"):
        period = int(p["period"])
        if index < period or len(closes) < period: return 0
        window = bars[index - period + 1:index + 1]
        typical = [(float(b.high) + float(b.low) + float(b.close)) / 3.0 for b in window]
        mean = fmean(typical)
        if spec.family == "CCI_REVERSION":
            mean_deviation = fmean([abs(value - mean) for value in typical])
            cci = 0.0 if mean_deviation == 0 else (typical[-1] - mean) / (0.015 * mean_deviation)
            threshold = float(p["threshold"])
            return 1 if cci <= -threshold else -1 if cci >= threshold else 0
        atr = float(_atr(bars, index, period)); multiplier = float(p["multiplier"])
        return 1 if closes[-1] > mean + atr * multiplier else -1 if closes[-1] < mean - atr * multiplier else 0
    if spec.family == "EMA_RSI_TREND":
        trend_period = int(p["trend"]); rsi_period = int(p["rsi_period"])
        if len(closes) < max(trend_period, rsi_period + 1): return 0
        trend = _ema(closes[-trend_period:], trend_period); rsi = _rsi(closes, rsi_period); pullback = float(p["pullback"])
        return 1 if closes[-1] > trend and rsi <= pullback else -1 if closes[-1] < trend and rsi >= 100 - pullback else 0
    if spec.family in ("ATR_CHANNEL_BREAKOUT", "BOLLINGER_BREAKOUT"):
        period = int(p["period"])
        if len(closes) < period: return 0
        center = fmean(closes[-period:])
        width = float(_atr(bars, index, period)) * float(p["multiplier"]) if spec.family == "ATR_CHANNEL_BREAKOUT" else pstdev(closes[-period:]) * float(p["deviation"])
        return 1 if closes[-1] > center + width else -1 if closes[-1] < center - width else 0
    if spec.family == "ROC_TREND_FILTER":
        period = int(p["period"]); trend_period = int(p["trend"])
        if len(closes) < max(period + 1, trend_period): return 0
        roc = 100.0 * (closes[-1] / closes[-period - 1] - 1.0); trend = _ema(closes[-trend_period:], trend_period); threshold = float(p["threshold"])
        return 1 if roc >= threshold and closes[-1] > trend else -1 if roc <= -threshold and closes[-1] < trend else 0
    if spec.family == "DONCHIAN_TREND_FILTER":
        lookback = int(p["entry_lookback"]); trend_period = int(p["trend"])
        if index < lookback or len(closes) < trend_period: return 0
        prior = bars[index - lookback:index]; trend = _ema(closes[-trend_period:], trend_period)
        return 1 if bars[index].close > max(bar.high for bar in prior) and closes[-1] > trend else -1 if bars[index].close < min(bar.low for bar in prior) and closes[-1] < trend else 0
    if spec.family == "STOCHASTIC_REVERSION":
        k_period = int(p["k_period"]); d_period = int(p["d_period"])
        if index < k_period + d_period: return 0
        ks = []
        for end in range(index - d_period + 1, index + 1):
            window = bars[end - k_period + 1:end + 1]
            low, high = min(float(b.low) for b in window), max(float(b.high) for b in window)
            ks.append(50.0 if high == low else 100.0 * (float(bars[end].close) - low) / (high - low))
        k, d = ks[-1], fmean(ks)
        return 1 if k <= float(p["lower"]) and k > d else -1 if k >= float(p["upper"]) and k < d else 0
    raise ValueError(f"Unsupported strategy family: {spec.family}")


def _atr(bars: tuple[Mt5Bar, ...], index: int, period: int = 14) -> Decimal:
    window = bars[max(0, index - period):index]
    return sum((bar.high - bar.low for bar in window), Decimal("0")) / max(1, len(window))


def _simulate(spec: StrategySpec, bars: tuple[Mt5Bar, ...], start: int, end: int, costs: CostModel) -> list[_Trade]:
    trades: list[_Trade] = []; index = max(start, 110)
    one_way_cost = costs.spread / Decimal("2") + costs.slippage
    while index < end - 1:
        side = _signal(spec, bars, index)
        if not side:
            index += 1; continue
        entry = bars[index].close + one_way_cost * side
        risk = _atr(bars, index) * Decimal(str(spec.atr_stop_multiplier))
        if risk <= 0:
            index += 1; continue
        stop = entry - risk * side; target = entry + risk * Decimal(str(spec.reward_risk_target)) * side
        exit_price = bars[min(index + 24, end - 1)].close - one_way_cost * side
        exit_index = min(index + 24, end - 1)
        for cursor in range(index + 1, min(index + 25, end)):
            bar = bars[cursor]
            stop_hit = bar.low <= stop if side > 0 else bar.high >= stop
            target_hit = bar.high >= target if side > 0 else bar.low <= target
            if stop_hit:
                exit_price, exit_index = stop - one_way_cost * side, cursor; break
            if target_hit:
                exit_price, exit_index = target - one_way_cost * side, cursor; break
        trades.append(_Trade((exit_price - entry) * side))
        index = exit_index + 1
    return trades


def _metrics(name: str, bars: int, trades: list[_Trade]) -> WindowMetrics:
    pnls = [trade.pnl for trade in trades]; gains = sum((p for p in pnls if p > 0), Decimal("0")); losses = abs(sum((p for p in pnls if p < 0), Decimal("0")))
    running = peak = drawdown = Decimal("0")
    for pnl in pnls:
        running += pnl; peak = max(peak, running); drawdown = max(drawdown, peak - running)
    return WindowMetrics(name=name, bars=bars, trades=len(pnls), net_pnl=sum(pnls, Decimal("0")), gross_profit=gains, gross_loss=losses, win_rate=Decimal(sum(p > 0 for p in pnls)) / len(pnls) if pnls else None, profit_factor=gains / losses if losses else None, expectancy=sum(pnls, Decimal("0")) / len(pnls) if pnls else None, maximum_drawdown=drawdown)


def _combine(windows: tuple[WindowMetrics, ...]) -> tuple[int, Decimal, Decimal | None, Decimal | None, Decimal]:
    trades = sum(w.trades for w in windows); net = sum((w.net_pnl for w in windows), Decimal("0")); drawdown = max((w.maximum_drawdown for w in windows), default=Decimal("0"))
    expectancy = net / trades if trades else None
    gross_losses = sum((w.gross_loss for w in windows), Decimal("0")); gross_gains = sum((w.gross_profit for w in windows), Decimal("0"))
    profit_factor = gross_gains / gross_losses if gross_losses else None
    return trades, net, profit_factor, expectancy, drawdown


def signal_fingerprint(spec: StrategySpec, bars: tuple[Mt5Bar, ...]) -> str:
    signals = bytes((_signal(spec, bars, i) + 1 for i in range(110, len(bars), 3)))
    return sha256(signals).hexdigest()


def evaluate_latest_signal(spec: StrategySpec, bars: tuple[Mt5Bar, ...]) -> str:
    value = _signal(spec, bars, len(bars) - 1)
    return "BUY" if value > 0 else "SELL" if value < 0 else "HOLD"


def validate_catalog(specs: tuple[StrategySpec, ...], bars: tuple[Mt5Bar, ...], costs: CostModel = CostModel()) -> tuple[CandidateValidation, ...]:
    if len(bars) < 600: raise ValueError("At least 600 chronological bars are required")
    # The final 20% is intentionally never inspected here. It is reserved for a
    # separate, one-shot finalization command after all research decisions lock.
    research_end = len(bars) * 4 // 5
    first, second = research_end * 3 // 4, research_end * 7 // 8
    results: list[CandidateValidation] = []; fingerprints: dict[str, str] = {}
    for spec in specs:
        fingerprint = signal_fingerprint(spec, bars); duplicate = fingerprints.get(fingerprint); fingerprints.setdefault(fingerprint, spec.version)
        in_sample = _metrics("IN_SAMPLE", first, _simulate(spec, bars, 0, first, costs))
        oos = (_metrics("OOS_1", second - first, _simulate(spec, bars, first, second, costs)), _metrics("OOS_2", research_end - second, _simulate(spec, bars, second, research_end, costs)))
        trades, net, profit_factor, expectancy, drawdown = _combine(oos); positive = sum(window.net_pnl > 0 for window in oos)
        reasons = []
        if duplicate: reasons.append(f"Duplicate signal fingerprint of {duplicate}")
        if trades < LOCKED_POLICY.minimum_walk_forward_trades: reasons.append(f"Fewer than {LOCKED_POLICY.minimum_walk_forward_trades} walk-forward trades")
        if net <= 0: reasons.append("Non-positive out-of-sample net P/L")
        if expectancy is None or expectancy <= 0: reasons.append("Non-positive out-of-sample expectancy")
        if profit_factor is not None and profit_factor < LOCKED_POLICY.minimum_profit_factor: reasons.append(f"Out-of-sample profit factor below {LOCKED_POLICY.minimum_profit_factor}")
        if positive < 2: reasons.append("Not profitable in every out-of-sample window")
        pf_score = float(min(profit_factor or Decimal("0"), Decimal("3")))
        dd_penalty = float(drawdown / (abs(net) + Decimal("0.0001")))
        robustness = Decimal(str(round(positive * 25 + min(trades, 40) + pf_score * 10 - dd_penalty * 10, 4)))
        results.append(CandidateValidation(version=spec.version, family=spec.family, signal_fingerprint=fingerprint, in_sample=in_sample, out_of_sample=oos, oos_net_pnl=net, oos_profit_factor=profit_factor, oos_expectancy=expectancy, oos_maximum_drawdown=drawdown, positive_oos_windows=positive, robustness_score=robustness, stable=not reasons, duplicate_of=duplicate, rejection_reasons=tuple(reasons)))
    ranked = sorted(results, key=lambda item: (item.stable, item.robustness_score, item.oos_expectancy or Decimal("-999")), reverse=True)
    return tuple(item.model_copy(update={"rank": rank}) for rank, item in enumerate(ranked, 1))
