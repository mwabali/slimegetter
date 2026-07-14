from pathlib import Path

import numpy as np

import pytest

from app.research.vectorized_validation import IndicatorCache, screen_candidates, signals_for, simulate
from app.strategies.catalog import CATALOG


def test_event_signals_and_costed_simulation_do_not_overlap() -> None:
    size = 1000
    close = 1800 + np.sin(np.arange(size) / 20) * 10
    cache = IndicatorCache(close.copy(), close + 1, close - 1, close)
    spec = next(row for row in CATALOG if row.family == "EMA_CROSS")
    signals = signals_for(spec, cache)
    assert np.count_nonzero(signals) < size // 4
    trades = simulate(signals, cache, 0, size, 1.5, 2.0, 0.30, 0.10)
    assert len(trades.pnl) > 0
    assert np.all(trades.entries[1:] > trades.exits[:-1])


def test_screen_rejects_ambiguous_microsecond_timestamps(tmp_path: Path) -> None:
    size = 100
    close = np.linspace(1800, 1810, size)
    dataset = tmp_path / "bad-time-unit.npz"
    np.savez_compressed(
        dataset,
        time=np.arange(size, dtype=np.int64) + 1_600_000_000_000_000,
        open=close,
        high=close + 1,
        low=close - 1,
        close=close,
    )
    with pytest.raises(ValueError, match="not nanoseconds"):
        screen_candidates((CATALOG[0],), str(dataset))


def test_risk_variants_are_not_classified_as_exact_duplicates(tmp_path: Path) -> None:
    size = 2000
    close = 1800 + np.sin(np.arange(size) / 17) * 12
    dataset = tmp_path / "risk-variants.npz"
    start = np.datetime64("2020-01-01T00:00", "ns").astype(np.int64)
    np.savez_compressed(
        dataset,
        time=start + np.arange(size, dtype=np.int64) * 300_000_000_000,
        open=close,
        high=close + 1,
        low=close - 1,
        close=close,
    )
    base = CATALOG[0]
    variant = base.model_copy(update={
        "version": "test-risk-variant@1.0",
        "atr_stop_multiplier": base.atr_stop_multiplier + 0.5,
    })
    rows, _, _ = screen_candidates((base, variant), str(dataset))
    assert rows[0]["duplicate_of"] is None
    assert rows[1]["duplicate_of"] is None
