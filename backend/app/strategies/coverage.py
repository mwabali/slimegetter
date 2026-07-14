"""Deterministic strategy-pool coverage and reserve planning.

The planner deliberately separates *availability* from *promotion*.  A
strategy can be assigned to a market situation and observed in shadow/paper
mode without gaining any MT5 execution authority.
"""

from dataclasses import dataclass
from typing import Iterable

from app.strategies.catalog import StrategySpec


SITUATIONS: tuple[str, ...] = (
    "TREND_UP",
    "TREND_DOWN",
    "RANGE",
    "BREAKOUT",
    "HIGH_VOLATILITY",
    "LOW_VOLATILITY",
    "WIDE_SPREAD",
    "NORMAL_LIQUIDITY",
    "ASIA_SESSION",
    "LONDON_SESSION",
    "NEW_YORK_SESSION",
    "LONDON_NEW_YORK_OVERLAP",
)

DEFAULT_MINIMUM_PER_SITUATION = 30
DEFAULT_RESERVE_POOL_SIZE = 100

_TREND_FAMILIES = {"EMA_CROSS", "MACD_MOMENTUM", "SMA_CROSS", "ROC_MOMENTUM", "EMA_RSI_TREND", "ROC_TREND_FILTER", "DONCHIAN_TREND_FILTER"}
_REVERSION_FAMILIES = {"RSI_REVERSION", "BOLLINGER_REVERSION", "STOCHASTIC_REVERSION", "CCI_REVERSION"}
_BREAKOUT_FAMILIES = {"DONCHIAN_BREAKOUT", "KELTNER_BREAKOUT", "ATR_CHANNEL_BREAKOUT", "BOLLINGER_BREAKOUT", "DONCHIAN_TREND_FILTER"}


@dataclass(frozen=True)
class SituationPlan:
    situation: str
    versions: tuple[str, ...]


@dataclass(frozen=True)
class CoveragePlan:
    situations: tuple[SituationPlan, ...]
    reserve_versions: tuple[str, ...]
    minimum_per_situation: int
    reserve_pool_size: int

    @property
    def planned_versions(self) -> tuple[str, ...]:
        return tuple(dict.fromkeys(version for bucket in self.situations for version in bucket.versions))


def _suitability(spec: StrategySpec, situation: str) -> int:
    """Prefer families that match a situation while retaining broad diversity."""
    family = spec.family
    if situation in {"TREND_UP", "TREND_DOWN"}:
        return 3 if family in _TREND_FAMILIES else 1
    if situation == "RANGE":
        return 3 if family in _REVERSION_FAMILIES else 1
    if situation == "BREAKOUT":
        return 3 if family in _BREAKOUT_FAMILIES else 1
    if situation == "HIGH_VOLATILITY":
        return 3 if family in _BREAKOUT_FAMILIES or family in _TREND_FAMILIES else 1
    if situation == "LOW_VOLATILITY":
        return 3 if family in _REVERSION_FAMILIES else 1
    return 2 if family in _TREND_FAMILIES or family in _REVERSION_FAMILIES else 1


def build_coverage_plan(
    specs: Iterable[StrategySpec],
    minimum_per_situation: int = DEFAULT_MINIMUM_PER_SITUATION,
    reserve_pool_size: int = DEFAULT_RESERVE_POOL_SIZE,
) -> CoveragePlan:
    """Build a reproducible core-plus-reserve plan from the catalog.

    Situation cohorts are distinct by default so the quota represents real
    breadth rather than repeating the same 30 versions in every bucket.
    Reserve versions are disjoint from the core plan so replacement capacity
    is preserved.
    """
    if minimum_per_situation < 1 or reserve_pool_size < 0:
        raise ValueError("coverage quotas must be non-negative and meaningful")
    ordered = tuple(sorted(specs, key=lambda spec: (spec.version, spec.family)))
    if len(ordered) < minimum_per_situation:
        raise ValueError("catalog is too small to satisfy one situation quota")
    buckets: list[SituationPlan] = []
    assigned: set[str] = set()
    for situation in SITUATIONS:
        ranked = sorted(ordered, key=lambda spec: (-_suitability(spec, situation), spec.version))
        selected = tuple(spec.version for spec in ranked if spec.version not in assigned)[:minimum_per_situation]
        if len(selected) < minimum_per_situation:
            raise ValueError("catalog is too small to provide distinct situation cohorts")
        assigned.update(selected)
        buckets.append(SituationPlan(situation, selected))
    reserve = tuple(spec.version for spec in ordered if spec.version not in assigned)[:reserve_pool_size]
    return CoveragePlan(tuple(buckets), reserve, minimum_per_situation, reserve_pool_size)


def coverage_status(plan: CoveragePlan, registered: dict[str, str]) -> dict[str, object]:
    """Return dashboard-safe counts without granting execution permission."""
    eligible = {"RESEARCH", "SHADOW_CANDIDATE", "SHADOW", "DEMO_CANDIDATE", "ACTIVE", "RESERVE"}
    situations = []
    reserve_eligible = [version for version in plan.reserve_versions if registered.get(version) in eligible]
    reserve_cursor = 0
    for bucket in plan.situations:
        statuses = [registered.get(version) for version in bucket.versions]
        eligible_count = sum(status in eligible for status in statuses)
        missing = max(0, len(bucket.versions) - eligible_count)
        replacements = min(missing, len(reserve_eligible) - reserve_cursor)
        reserve_cursor += replacements
        situations.append({
            "situation": bucket.situation,
            "required": plan.minimum_per_situation,
            "planned": len(bucket.versions),
            "registered": sum(status is not None for status in statuses),
            "eligible": eligible_count,
            "replacement_candidates": replacements,
            "shadow_or_active": sum(status in {"SHADOW_CANDIDATE", "SHADOW", "DEMO_CANDIDATE", "ACTIVE"} for status in statuses),
            "versions": list(bucket.versions),
        })
    reserve_statuses = [registered.get(version) for version in plan.reserve_versions]
    return {
        "minimum_per_situation": plan.minimum_per_situation,
        "reserve_pool_required": plan.reserve_pool_size,
        "catalog_planned": len(plan.planned_versions),
        "reserve_planned": len(plan.reserve_versions),
        "coverage_complete": all(item["planned"] >= item["required"] for item in situations),
        "operational_core_complete": all(item["eligible"] + item["replacement_candidates"] >= item["required"] for item in situations),
        "reserve_complete": len(plan.reserve_versions) >= plan.reserve_pool_size,
        "reserve_registered": sum(status is not None for status in reserve_statuses),
        "reserve_eligible": len(reserve_eligible),
        "reserve_replacements_used": reserve_cursor,
        "reserve_available_after_replacement": max(0, len(reserve_eligible) - reserve_cursor),
        "situations": situations,
        "reserve_versions": list(plan.reserve_versions),
    }
