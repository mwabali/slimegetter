"""Build a reproducible XAUUSD M5 research dataset from HistData ZIP archives."""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from zipfile import ZipFile

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class BuildResult:
    manifest_path: Path
    development_path: Path
    holdout_path: Path
    manifest: dict[str, object]


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _read_archive(path: Path) -> pd.DataFrame:
    with ZipFile(path) as archive:
        names = [name for name in archive.namelist() if name.lower().endswith(".csv")]
        if len(names) != 1:
            raise ValueError(f"Expected one CSV in {path.name}, found {len(names)}")
        with archive.open(names[0]) as stream:
            frame = pd.read_csv(
                stream, sep=";", header=None,
                names=("timestamp", "open", "high", "low", "close", "volume"),
                dtype={"timestamp": "string", "open": "float64", "high": "float64", "low": "float64", "close": "float64", "volume": "float64"},
            )
    # HistData documents fixed EST (UTC-5), explicitly without DST adjustment.
    local = pd.to_datetime(frame.pop("timestamp"), format="%Y%m%d %H%M%S", errors="raise")
    frame.index = local.dt.tz_localize("Etc/GMT+5").dt.tz_convert("UTC")
    return frame


def _write_npz(path: Path, frame: pd.DataFrame) -> None:
    # Pandas may retain a microsecond-resolution DatetimeIndex depending on the
    # parser/version.  Persist an explicit nanosecond contract so downstream
    # statistical grouping cannot silently interpret microseconds as ns.
    timestamps_ns = (
        frame.index.tz_convert("UTC").tz_localize(None)
        .to_numpy(dtype="datetime64[ns]").astype("int64")
    )
    np.savez_compressed(
        path,
        time=timestamps_ns,
        open=frame["open"].to_numpy(dtype="float64"),
        high=frame["high"].to_numpy(dtype="float64"),
        low=frame["low"].to_numpy(dtype="float64"),
        close=frame["close"].to_numpy(dtype="float64"),
        source_minutes=frame["source_minutes"].to_numpy(dtype="uint8"),
    )


def build_histdata_dataset(archive_dir: Path, output_dir: Path) -> BuildResult:
    archives = sorted(archive_dir.glob("xauusd_m1_*.zip"))
    if len(archives) < 3:
        raise ValueError("At least three annual archives are required")
    raw = pd.concat((_read_archive(path) for path in archives)).sort_index()
    duplicate_rows = int(raw.index.duplicated(keep=False).sum())
    duplicate_slice = raw[raw.index.duplicated(keep=False)]
    conflicting_duplicate_timestamps = int(
        (duplicate_slice.groupby(level=0)[["open", "high", "low", "close"]].nunique().max(axis=1) > 1).sum()
    ) if duplicate_rows else 0
    raw = raw[~raw.index.duplicated(keep="first")]
    invalid_ohlc = int(((raw.low > raw[["open", "close"]].min(axis=1)) | (raw.high < raw[["open", "close"]].max(axis=1)) | (raw.high < raw.low)).sum())
    nonpositive = int((raw[["open", "high", "low", "close"]] <= 0).any(axis=1).sum())
    if conflicting_duplicate_timestamps or invalid_ohlc or nonpositive:
        raise ValueError(f"Raw QA failed: conflicting_duplicates={conflicting_duplicate_timestamps}, invalid_ohlc={invalid_ohlc}, nonpositive={nonpositive}")

    m5 = raw.resample("5min", origin="epoch", label="left", closed="left").agg(
        open=("open", "first"), high=("high", "max"), low=("low", "min"),
        close=("close", "last"), source_minutes=("close", "count"),
    ).dropna(subset=["open", "high", "low", "close"])
    returns = m5.close.pct_change().abs()
    extreme_returns = int((returns > 0.10).sum())
    timestamps = (
        m5.index.tz_convert("UTC").tz_localize(None)
        .to_numpy(dtype="datetime64[ns]").astype("int64")
    )
    nonmonotonic = int(np.sum(np.diff(timestamps) <= 0))
    partial_bars = int((m5.source_minutes < 5).sum())
    calendar_years = sorted({int(value) for value in m5.index.year})
    if len(calendar_years) < 3 or extreme_returns or nonmonotonic:
        raise ValueError(f"M5 QA failed: years={len(calendar_years)}, extreme_returns={extreme_returns}, nonmonotonic={nonmonotonic}")

    split = int(len(m5) * 0.80)
    development, holdout = m5.iloc[:split], m5.iloc[split:]
    output_dir.mkdir(parents=True, exist_ok=True)
    development_path = output_dir / "xauusd_m5_development_80pct.npz"
    holdout_path = output_dir / "xauusd_m5_UNTOUCHED_holdout_20pct.npz"
    _write_npz(development_path, development)
    _write_npz(holdout_path, holdout)
    archive_hashes = {path.name: _sha256(path) for path in archives}
    manifest: dict[str, object] = {
        "schema_version": "histdata-xauusd-m5@1.0.0",
        "timestamp_unit": "nanoseconds_since_unix_epoch",
        "created_at_utc": datetime.now(UTC).isoformat(),
        "source": "HistData Generic ASCII M1 bid OHLC",
        "source_timezone": "fixed EST UTC-05:00 without DST",
        "years": calendar_years,
        "raw_rows": int(len(raw)), "m5_rows": int(len(m5)),
        "start_utc": m5.index[0].isoformat(), "end_utc": m5.index[-1].isoformat(),
        "partial_m5_bars": partial_bars, "duplicate_rows": duplicate_rows,
        "conflicting_duplicate_timestamps": conflicting_duplicate_timestamps,
        "invalid_ohlc_rows": invalid_ohlc, "nonpositive_rows": nonpositive,
        "extreme_five_minute_returns_over_10pct": extreme_returns,
        "development_rows": int(len(development)), "holdout_rows": int(len(holdout)),
        "development_end_utc": development.index[-1].isoformat(),
        "holdout_start_utc": holdout.index[0].isoformat(),
        "holdout_opened": False,
        "archive_sha256": archive_hashes,
        "development_sha256": _sha256(development_path),
        "holdout_sha256": _sha256(holdout_path),
        "limitations": ["Bid-only OHLC", "zero/placeholder volume", "broker-independent pricing"],
    }
    manifest_path = output_dir / "xauusd_m5_manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return BuildResult(manifest_path, development_path, holdout_path, manifest)
