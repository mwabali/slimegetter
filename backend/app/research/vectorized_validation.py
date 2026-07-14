"""Efficient, event-driven validation over the frozen development dataset."""
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from decimal import Decimal
from statistics import fmean

import numpy as np
import pandas as pd

from app.research.statistical_controls import HypothesisResult, benjamini_hochberg, newey_west_mean_p_value
from app.strategies.catalog import StrategySpec
from app.strategies.validation_policy import LOCKED_POLICY


@dataclass(frozen=True)
class TradeSet:
    entries: np.ndarray
    exits: np.ndarray
    pnl: np.ndarray


class IndicatorCache:
    def __init__(self, open_: np.ndarray, high: np.ndarray, low: np.ndarray, close: np.ndarray) -> None:
        self.open, self.high, self.low, self.close = open_, high, low, close
        self.series = pd.Series(close)
        self._cache: dict[tuple[object, ...], np.ndarray] = {}

    def ema(self, period: int) -> np.ndarray:
        key = ("ema", period)
        if key not in self._cache:
            self._cache[key] = self.series.ewm(span=period, adjust=False, min_periods=period).mean().to_numpy()
        return self._cache[key]

    def sma(self, period: int) -> np.ndarray:
        key = ("sma", period)
        if key not in self._cache:
            self._cache[key] = self.series.rolling(period).mean().to_numpy()
        return self._cache[key]

    def std(self, period: int) -> np.ndarray:
        key = ("std", period)
        if key not in self._cache:
            self._cache[key] = self.series.rolling(period).std(ddof=0).to_numpy()
        return self._cache[key]

    def atr(self, period: int = 14) -> np.ndarray:
        key = ("atr", period)
        if key not in self._cache:
            previous = np.roll(self.close, 1); previous[0] = self.close[0]
            true_range = np.maximum(self.high - self.low, np.maximum(abs(self.high - previous), abs(self.low - previous)))
            self._cache[key] = pd.Series(true_range).rolling(period).mean().to_numpy()
        return self._cache[key]

    def rolling_high(self, period: int) -> np.ndarray:
        key = ("high", period)
        if key not in self._cache:
            self._cache[key] = pd.Series(self.high).rolling(period).max().shift(1).to_numpy()
        return self._cache[key]

    def rolling_low(self, period: int) -> np.ndarray:
        key = ("low", period)
        if key not in self._cache:
            self._cache[key] = pd.Series(self.low).rolling(period).min().shift(1).to_numpy()
        return self._cache[key]

    def rsi(self, period: int) -> np.ndarray:
        key = ("rsi", period)
        if key not in self._cache:
            delta = self.series.diff(); gain = delta.clip(lower=0).rolling(period).mean(); loss = (-delta.clip(upper=0)).rolling(period).mean()
            self._cache[key] = (100 - 100 / (1 + gain / loss.replace(0, np.nan))).fillna(100).to_numpy()
        return self._cache[key]

    def stochastic(self, period: int) -> np.ndarray:
        key = ("stochastic", period)
        if key not in self._cache:
            lo = pd.Series(self.low).rolling(period).min(); hi = pd.Series(self.high).rolling(period).max()
            self._cache[key] = (100 * (self.series - lo) / (hi - lo).replace(0, np.nan)).to_numpy()
        return self._cache[key]

    def cci(self, period: int) -> np.ndarray:
        key = ("cci", period)
        if key not in self._cache:
            typical = pd.Series((self.high + self.low + self.close) / 3)
            mean = typical.rolling(period).mean()
            deviation = typical.rolling(period).apply(lambda values: np.mean(np.abs(values - np.mean(values))), raw=True)
            self._cache[key] = ((typical - mean) / (0.015 * deviation.replace(0, np.nan))).to_numpy()
        return self._cache[key]


def _events(state: np.ndarray) -> np.ndarray:
    state = np.nan_to_num(state, nan=0).astype(np.int8)
    previous = np.roll(state, 1); previous[0] = 0
    return np.where((state != 0) & (state != previous), state, 0).astype(np.int8)


def signals_for(spec: StrategySpec, cache: IndicatorCache) -> np.ndarray:
    p, close = spec.parameters, cache.close
    if spec.family in ("EMA_CROSS", "SMA_CROSS"):
        getter = cache.ema if spec.family == "EMA_CROSS" else cache.sma
        difference = getter(int(p["fast"])) - getter(int(p["slow"]))
        return _events(np.sign(difference))
    if spec.family == "DONCHIAN_BREAKOUT":
        period = int(p["entry_lookback"])
        return _events(np.where(close > cache.rolling_high(period), 1, np.where(close < cache.rolling_low(period), -1, 0)))
    if spec.family == "RSI_REVERSION":
        value = cache.rsi(int(p["period"]))
        return _events(np.where(value <= float(p["lower"]), 1, np.where(value >= float(p["upper"]), -1, 0)))
    if spec.family == "BOLLINGER_REVERSION":
        period = int(p["period"]); mean = cache.sma(period); width = cache.std(period) * float(p["deviation"])
        return _events(np.where(close < mean - width, 1, np.where(close > mean + width, -1, 0)))
    if spec.family == "MACD_MOMENTUM":
        macd = cache.ema(int(p["fast"])) - cache.ema(int(p["slow"]))
        signal = pd.Series(macd).ewm(span=int(p["signal"]), adjust=False, min_periods=int(p["signal"])).mean().to_numpy()
        return _events(np.sign(macd - signal))
    if spec.family == "STOCHASTIC_REVERSION":
        k = cache.stochastic(int(p["k_period"])); d = pd.Series(k).rolling(int(p["d_period"])).mean().to_numpy()
        return _events(np.where((k <= float(p["lower"])) & (k > d), 1, np.where((k >= float(p["upper"])) & (k < d), -1, 0)))
    if spec.family == "ROC_MOMENTUM":
        period = int(p["period"]); roc = pd.Series(close).pct_change(period).to_numpy() * 100; threshold = float(p["threshold"])
        return _events(np.where(roc >= threshold, 1, np.where(roc <= -threshold, -1, 0)))
    if spec.family == "CCI_REVERSION":
        cci = cache.cci(int(p["period"])); threshold = float(p["threshold"])
        return _events(np.where(cci <= -threshold, 1, np.where(cci >= threshold, -1, 0)))
    if spec.family == "KELTNER_BREAKOUT":
        period = int(p["period"]); center = cache.ema(period); width = cache.atr(period) * float(p["multiplier"])
        return _events(np.where(close > center + width, 1, np.where(close < center - width, -1, 0)))
    if spec.family == "EMA_RSI_TREND":
        trend = cache.ema(int(p["trend"])); rsi = cache.rsi(int(p["rsi_period"])); pullback = float(p["pullback"])
        return _events(np.where((close > trend) & (rsi <= pullback), 1, np.where((close < trend) & (rsi >= 100 - pullback), -1, 0)))
    if spec.family == "ATR_CHANNEL_BREAKOUT":
        period = int(p["period"]); center = cache.sma(period); width = cache.atr(period) * float(p["multiplier"])
        return _events(np.where(close > center + width, 1, np.where(close < center - width, -1, 0)))
    if spec.family == "BOLLINGER_BREAKOUT":
        period = int(p["period"]); center = cache.sma(period); width = cache.std(period) * float(p["deviation"])
        return _events(np.where(close > center + width, 1, np.where(close < center - width, -1, 0)))
    if spec.family == "ROC_TREND_FILTER":
        period = int(p["period"]); trend = cache.ema(int(p["trend"])); threshold = float(p["threshold"])
        roc = pd.Series(close).pct_change(period).to_numpy() * 100
        return _events(np.where((roc >= threshold) & (close > trend), 1, np.where((roc <= -threshold) & (close < trend), -1, 0)))
    if spec.family == "DONCHIAN_TREND_FILTER":
        trend = cache.ema(int(p["trend"])); period = int(p["entry_lookback"])
        return _events(np.where((close > cache.rolling_high(period)) & (close > trend), 1, np.where((close < cache.rolling_low(period)) & (close < trend), -1, 0)))
    raise ValueError(f"Unsupported strategy family: {spec.family}")


def simulate(
    signals: np.ndarray, cache: IndicatorCache, start: int, end: int,
    stop_multiplier: float, reward_risk: float, spread: float, slippage: float,
    maximum_holding_bars: int = 24,
) -> TradeSet:
    candidates = np.flatnonzero(signals[start:end]) + start
    atr = cache.atr(14); one_way_cost = spread / 2 + slippage
    entries: list[int] = []; exits: list[int] = []; pnls: list[float] = []
    available_at = start
    for index in candidates:
        if index < available_at or index >= end - 1 or not np.isfinite(atr[index]) or atr[index] <= 0:
            continue
        side = int(signals[index]); entry = cache.close[index] + one_way_cost * side
        risk = atr[index] * stop_multiplier; stop = entry - risk * side; target = entry + risk * reward_risk * side
        final = min(index + maximum_holding_bars, end - 1); exit_index = final; exit_price = cache.close[final] - one_way_cost * side
        for cursor in range(index + 1, final + 1):
            stop_hit = cache.low[cursor] <= stop if side > 0 else cache.high[cursor] >= stop
            target_hit = cache.high[cursor] >= target if side > 0 else cache.low[cursor] <= target
            if stop_hit:  # conservative ordering when both barriers occur in one OHLC bar
                exit_index, exit_price = cursor, stop - one_way_cost * side; break
            if target_hit:
                exit_index, exit_price = cursor, target - one_way_cost * side; break
        entries.append(index); exits.append(exit_index); pnls.append((exit_price - entry) * side)
        available_at = exit_index + 1
    return TradeSet(np.asarray(entries, dtype=np.int32), np.asarray(exits, dtype=np.int32), np.asarray(pnls, dtype=np.float64))


def metrics(trades: TradeSet) -> dict[str, float | int | None]:
    pnl = trades.pnl; gains = float(pnl[pnl > 0].sum()); losses = float(-pnl[pnl < 0].sum()); net = float(pnl.sum())
    curve = np.cumsum(pnl); drawdown = float(np.max(np.maximum.accumulate(np.r_[0.0, curve])[1:] - curve)) if len(curve) else 0.0
    return {
        "trades": int(len(pnl)), "net_pnl": net, "gross_profit": gains, "gross_loss": losses,
        "profit_factor": gains / losses if losses else None,
        "expectancy": net / len(pnl) if len(pnl) else None,
        "win_rate": float(np.mean(pnl > 0)) if len(pnl) else None,
        "maximum_drawdown": drawdown,
    }


def screen_candidates(
    specs: tuple[StrategySpec, ...], dataset_path: str, spread: float = 0.30, slippage: float = 0.10,
) -> tuple[list[dict[str, object]], dict[str, np.ndarray], np.ndarray]:
    with np.load(dataset_path) as data:
        time = data["time"].copy(); cache = IndicatorCache(data["open"], data["high"], data["low"], data["close"])
    if len(time) and int(time[0]) < 100_000_000_000_000_000:
        raise ValueError("Dataset timestamps are not nanoseconds since Unix epoch; rebuild the research dataset")
    first = int(len(time) * 0.75); second = first + (len(time) - first) // 2
    results: list[dict[str, object]] = []; returns_by_version: dict[str, np.ndarray] = {}; fingerprints: dict[str, str] = {}
    hypotheses: list[HypothesisResult] = []
    for spec in specs:
        signals = signals_for(spec, cache)
        # A complete strategy candidate includes its entries *and* deterministic
        # exit/risk policy.  Signal-only hashing incorrectly collapsed distinct
        # ATR-stop and reward/risk variants into duplicates.  Highly similar
        # realized returns are handled later by the correlation filter.
        fingerprint_payload = b"|".join((
            signals.tobytes(),
            np.float64(spec.atr_stop_multiplier).tobytes(),
            np.float64(spec.reward_risk_target).tobytes(),
            np.int64(24).tobytes(),
        ))
        fingerprint = hashlib.sha256(fingerprint_payload).hexdigest(); duplicate_of = fingerprints.get(fingerprint); fingerprints.setdefault(fingerprint, spec.version)
        train = simulate(signals, cache, 0, first, spec.atr_stop_multiplier, spec.reward_risk_target, spread, slippage)
        wf1 = simulate(signals, cache, first, second, spec.atr_stop_multiplier, spec.reward_risk_target, spread, slippage)
        wf2 = simulate(signals, cache, second, len(time), spec.atr_stop_multiplier, spec.reward_risk_target, spread, slippage)
        combined = TradeSet(np.r_[wf1.entries, wf2.entries], np.r_[wf1.exits, wf2.exits], np.r_[wf1.pnl, wf2.pnl])
        train_metrics, first_metrics, second_metrics, combined_metrics = metrics(train), metrics(wf1), metrics(wf2), metrics(combined)
        reasons: list[str] = []
        if duplicate_of: reasons.append(f"Exact duplicate of {duplicate_of}")
        if combined_metrics["trades"] < LOCKED_POLICY.minimum_walk_forward_trades: reasons.append("Insufficient walk-forward trades")
        if combined_metrics["net_pnl"] <= 0 or (combined_metrics["expectancy"] or 0) <= 0: reasons.append("Non-positive walk-forward expectancy")
        if (combined_metrics["profit_factor"] or 0) < float(LOCKED_POLICY.minimum_profit_factor): reasons.append("Walk-forward profit factor below threshold")
        if first_metrics["net_pnl"] <= 0 or second_metrics["net_pnl"] <= 0: reasons.append("Not profitable in both walk-forward windows")
        days = time.astype("datetime64[ns]").astype("datetime64[D]")
        unique_days = np.unique(days[first:])
        daily_pnl = np.zeros(len(unique_days), dtype=np.float64)
        if len(combined.exits):
            np.add.at(daily_pnl, np.searchsorted(unique_days, days[combined.exits]), combined.pnl)
        p_value = newey_west_mean_p_value(tuple(float(value) for value in daily_pnl))
        hypotheses.append(HypothesisResult(spec.version, p_value))
        if not reasons:
            returns_by_version[spec.version] = np.column_stack((combined.exits, combined.pnl)).astype(np.float64)
        results.append({
            "version": spec.version, "family": spec.family, "fingerprint": fingerprint,
            "duplicate_of": duplicate_of, "train": train_metrics, "walk_forward_1": first_metrics,
            "walk_forward_2": second_metrics, "walk_forward": combined_metrics,
            "p_value": p_value, "base_stable": not reasons, "rejection_reasons": reasons,
        })
    fdr = {row.version: row for row in benjamini_hochberg(tuple(hypotheses), float(LOCKED_POLICY.false_discovery_rate))}
    for row in results:
        control = fdr[str(row["version"])]
        row["fdr_adjusted_p_value"] = control.adjusted_p_value; row["passes_fdr"] = control.passes_fdr
        if not control.passes_fdr: row["rejection_reasons"].append("Failed Benjamini-Hochberg false-discovery control")
        row["statistically_stable"] = bool(row["base_stable"] and control.passes_fdr)
    return results, returns_by_version, time
