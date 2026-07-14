"""Freeze development survivors after multiplicity, neighborhood and correlation gates."""
from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

import numpy as np

from app.research.vectorized_validation import screen_candidates
from app.strategies.catalog import StrategySpec
from app.strategies.validation_policy import LOCKED_POLICY


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _ranking_score(row: dict[str, object]) -> float:
    wf = row["walk_forward"]
    assert isinstance(wf, dict)
    profit_factor = min(float(wf.get("profit_factor") or 0), 3.0)
    expectancy = float(wf.get("expectancy") or 0)
    net = abs(float(wf.get("net_pnl") or 0))
    drawdown = float(wf.get("maximum_drawdown") or 0)
    trades = int(wf.get("trades") or 0)
    return 30 * profit_factor + 10 * expectancy + min(trades, 500) / 25 - 20 * drawdown / (net + 1e-9)


def _numeric_vector(spec: StrategySpec, keys: tuple[str, ...]) -> np.ndarray:
    return np.asarray([float(spec.parameters.get(key, 0)) for key in keys] + [spec.atr_stop_multiplier, spec.reward_risk_target])


def _neighborhood_support(specs: tuple[StrategySpec, ...], stable: set[str]) -> dict[str, int]:
    result: dict[str, int] = {}
    by_family: dict[str, list[StrategySpec]] = {}
    for spec in specs: by_family.setdefault(spec.family, []).append(spec)
    for family_specs in by_family.values():
        keys = tuple(sorted({key for spec in family_specs for key, value in spec.parameters.items() if isinstance(value, (int, float))}))
        matrix = np.vstack([_numeric_vector(spec, keys) for spec in family_specs])
        scale = np.ptp(matrix, axis=0); scale[scale == 0] = 1
        normalized = (matrix - matrix.min(axis=0)) / scale
        for index, spec in enumerate(family_specs):
            distances = np.linalg.norm(normalized - normalized[index], axis=1); distances[index] = np.inf
            neighbors = np.argsort(distances)[:5]
            result[spec.version] = sum(family_specs[position].version in stable for position in neighbors)
    return result


def _correlation_leaders(
    ranked: list[dict[str, object]], sparse_returns: dict[str, np.ndarray], time: np.ndarray,
) -> dict[str, str | None]:
    days = time.astype("datetime64[ns]").astype("datetime64[D]"); unique_days = np.unique(days)
    selected: list[tuple[str, np.ndarray]] = []; decisions: dict[str, str | None] = {}
    for row in ranked:
        version = str(row["version"]); sparse = sparse_returns.get(version)
        if sparse is None: continue
        daily = np.zeros(len(unique_days), dtype=np.float64)
        exits = sparse[:, 0].astype(np.int64); np.add.at(daily, np.searchsorted(unique_days, days[exits]), sparse[:, 1])
        duplicate = None
        for leader, leader_daily in selected:
            if np.std(daily) and np.std(leader_daily) and abs(float(np.corrcoef(daily, leader_daily)[0, 1])) >= float(LOCKED_POLICY.maximum_signal_correlation):
                duplicate = leader; break
        decisions[version] = duplicate
        if duplicate is None: selected.append((version, daily))
    return decisions


def run_development_screen(
    specs: tuple[StrategySpec, ...], dataset_path: Path, manifest_path: Path,
    output_path: Path, spread: float = 0.30, slippage: float = 0.10,
) -> dict[str, object]:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest["development_sha256"] != _sha256(dataset_path):
        raise ValueError("Development dataset hash does not match frozen manifest")
    if manifest.get("holdout_opened") is not False:
        raise ValueError("Holdout state is not pristine")
    results, sparse_returns, time = screen_candidates(specs, str(dataset_path), spread, slippage)
    initially_stable = {str(row["version"]) for row in results if row["statistically_stable"]}
    support = _neighborhood_support(specs, initially_stable)
    for row in results:
        row["stable_neighbor_count_among_5_nearest"] = support[str(row["version"])]
        if row["statistically_stable"] and support[str(row["version"])] < 2:
            row["rejection_reasons"].append("Insufficient local parameter-neighborhood stability")
            row["statistically_stable"] = False
        row["ranking_score"] = _ranking_score(row)
    ranked = sorted((row for row in results if row["statistically_stable"]), key=lambda row: float(row["ranking_score"]), reverse=True)
    correlations = _correlation_leaders(ranked, sparse_returns, time)
    for row in ranked:
        row["correlated_with"] = correlations.get(str(row["version"]))
        if row["correlated_with"]:
            row["rejection_reasons"].append(f"Daily P/L correlation >= {LOCKED_POLICY.maximum_signal_correlation} with {row['correlated_with']}")
    survivors = [row for row in ranked if not row.get("correlated_with")][:100]
    selected = {str(row["version"]) for row in survivors}
    for row in results: row["development_survivor"] = str(row["version"]) in selected
    catalog_json = json.dumps([spec.model_dump(mode="json") for spec in specs], sort_keys=True, separators=(",", ":"))
    report: dict[str, object] = {
        "schema_version": "xauusd-development-screen@2.0.0",
        "created_at_utc": datetime.now(UTC).isoformat(), "policy": LOCKED_POLICY.model_dump(mode="json"),
        "dataset_manifest_sha256": _sha256(manifest_path), "development_dataset_sha256": _sha256(dataset_path),
        "catalog_sha256": hashlib.sha256(catalog_json.encode()).hexdigest(), "candidate_count": len(specs),
        "cost_model": {"spread": spread, "slippage_per_side": slippage},
        "base_and_fdr_stable_count": len(initially_stable), "after_neighborhood_and_correlation_count": len(survivors),
        "survivor_versions": [row["version"] for row in survivors], "results": results,
        "holdout_used": False,
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    return report
