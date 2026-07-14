"""Predeclared multiple-testing and correlated-candidate controls."""
from __future__ import annotations

from dataclasses import dataclass
from math import sqrt
from statistics import fmean, NormalDist


@dataclass(frozen=True)
class HypothesisResult:
    version: str
    p_value: float
    passes_fdr: bool = False
    adjusted_p_value: float = 1.0


def one_sided_mean_p_value(returns: tuple[float, ...]) -> float:
    """Approximate one-sided test that mean net return is greater than zero."""
    if len(returns) < 2:
        return 1.0
    mean = fmean(returns)
    variance = sum((value - mean) ** 2 for value in returns) / (len(returns) - 1)
    if variance <= 0:
        return 0.0 if mean > 0 else 1.0
    statistic = mean / sqrt(variance / len(returns))
    return 1.0 - NormalDist().cdf(statistic)


def newey_west_mean_p_value(returns: tuple[float, ...], maximum_lag: int | None = None) -> float:
    """One-sided mean test with HAC variance for serially dependent daily P/L."""
    count = len(returns)
    if count < 20:
        return 1.0
    values = [float(value) for value in returns]
    mean = fmean(values); centered = [value - mean for value in values]
    lag = maximum_lag if maximum_lag is not None else max(1, int(4 * (count / 100) ** (2 / 9)))
    gamma0 = sum(value * value for value in centered) / count
    long_run = gamma0
    for offset in range(1, min(lag, count - 1) + 1):
        covariance = sum(centered[index] * centered[index - offset] for index in range(offset, count)) / count
        long_run += 2 * (1 - offset / (lag + 1)) * covariance
    if long_run <= 0:
        return 0.0 if mean > 0 else 1.0
    statistic = mean / sqrt(long_run / count)
    return 1.0 - NormalDist().cdf(statistic)


def benjamini_hochberg(hypotheses: tuple[HypothesisResult, ...], q: float = 0.05) -> tuple[HypothesisResult, ...]:
    """Control false discovery rate across the full candidate universe."""
    if not 0 < q < 1:
        raise ValueError("q must be between zero and one")
    ordered = sorted(hypotheses, key=lambda item: (item.p_value, item.version))
    count = len(ordered)
    largest = 0
    for rank, item in enumerate(ordered, 1):
        if item.p_value <= q * rank / max(1, count):
            largest = rank
    adjusted: list[HypothesisResult] = []
    running = 1.0
    raw_adjusted = [min(1.0, item.p_value * count / rank) for rank, item in enumerate(ordered, 1)]
    for index in range(count - 1, -1, -1):
        running = min(running, raw_adjusted[index])
        item = ordered[index]
        adjusted.append(HypothesisResult(item.version, item.p_value, index + 1 <= largest, running))
    return tuple(sorted(reversed(adjusted), key=lambda item: item.version))


def pearson(left: tuple[float, ...], right: tuple[float, ...]) -> float:
    if len(left) != len(right) or len(left) < 2:
        raise ValueError("Equal series with at least two observations are required")
    left_mean, right_mean = fmean(left), fmean(right)
    numerator = sum((x - left_mean) * (y - right_mean) for x, y in zip(left, right, strict=True))
    left_scale = sqrt(sum((x - left_mean) ** 2 for x in left))
    right_scale = sqrt(sum((y - right_mean) ** 2 for y in right))
    if left_scale == 0 or right_scale == 0:
        return 1.0 if left == right else 0.0
    return numerator / (left_scale * right_scale)


def select_uncorrelated(
    ranked_returns: tuple[tuple[str, tuple[float, ...]], ...], threshold: float = 0.90,
) -> tuple[tuple[str, str | None], ...]:
    """Greedily retain ranked leaders and label highly correlated followers."""
    selected: list[tuple[str, tuple[float, ...]]] = []
    decisions: list[tuple[str, str | None]] = []
    for version, returns in ranked_returns:
        duplicate = next((leader for leader, series in selected if abs(pearson(returns, series)) >= threshold), None)
        decisions.append((version, duplicate))
        if duplicate is None:
            selected.append((version, returns))
    return tuple(decisions)
