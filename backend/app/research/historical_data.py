"""Authenticated, read-only OANDA candle ingestion and reproducible dataset QA."""
from __future__ import annotations

import csv
import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any, Callable, Iterable
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from pydantic import BaseModel, ConfigDict


class HistoricalCandle(BaseModel):
    model_config = ConfigDict(frozen=True)
    time: datetime
    bid_open: Decimal
    bid_high: Decimal
    bid_low: Decimal
    bid_close: Decimal
    ask_open: Decimal
    ask_high: Decimal
    ask_low: Decimal
    ask_close: Decimal
    volume: int

    @property
    def spread_close(self) -> Decimal:
        return self.ask_close - self.bid_close


class DatasetManifest(BaseModel):
    model_config = ConfigDict(frozen=True)
    provider: str
    instrument: str
    granularity: str
    start: datetime
    end: datetime
    rows: int
    calendar_years: int
    duplicate_timestamps: int
    invalid_ohlc_rows: int
    negative_spread_rows: int
    weekday_gaps_over_5_minutes: int
    median_close_spread: Decimal
    sha256: str
    suitable_for_final_validation: bool


@dataclass(frozen=True)
class OandaCandleClient:
    token: str
    base_url: str = "https://api-fxpractice.oanda.com"
    opener: Callable[..., Any] = urlopen

    def _request(self, instrument: str, start: datetime, end: datetime) -> list[dict[str, Any]]:
        query = urlencode({
            "price": "BA", "granularity": "M5", "from": _iso(start),
            "to": _iso(end), "smooth": "false", "includeFirst": "true",
        })
        request = Request(
            f"{self.base_url}/v3/instruments/{instrument}/candles?{query}",
            headers={"Authorization": f"Bearer {self.token}", "Accept-Datetime-Format": "RFC3339"},
        )
        with self.opener(request, timeout=30) as response:
            payload = json.loads(response.read())
        return [row for row in payload.get("candles", ()) if row.get("complete") and row.get("bid") and row.get("ask")]

    def fetch(self, instrument: str, start: datetime, end: datetime) -> tuple[HistoricalCandle, ...]:
        if not self.token.strip():
            raise ValueError("OANDA token is required and must be supplied from the environment")
        if start.tzinfo is None or end.tzinfo is None or start >= end:
            raise ValueError("UTC-aware start before end is required")
        rows: dict[datetime, HistoricalCandle] = {}
        cursor = start.astimezone(UTC)
        # Fourteen days contains at most 4,032 M5 intervals, below OANDA's
        # documented 5,000-candle response limit.
        while cursor < end:
            boundary = min(cursor + timedelta(days=14), end)
            for raw in self._request(instrument, cursor, boundary):
                candle = _parse_candle(raw)
                rows[candle.time] = candle
            cursor = boundary
        return tuple(rows[key] for key in sorted(rows))


def _iso(value: datetime) -> str:
    return value.astimezone(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def _parse_time(value: str) -> datetime:
    head, dot, tail = value.rstrip("Z").partition(".")
    normalized = f"{head}.{tail[:6]}" if dot else head
    return datetime.fromisoformat(normalized).replace(tzinfo=UTC)


def _parse_candle(raw: dict[str, Any]) -> HistoricalCandle:
    bid, ask = raw["bid"], raw["ask"]
    return HistoricalCandle(
        time=_parse_time(raw["time"]),
        bid_open=bid["o"], bid_high=bid["h"], bid_low=bid["l"], bid_close=bid["c"],
        ask_open=ask["o"], ask_high=ask["h"], ask_low=ask["l"], ask_close=ask["c"],
        volume=int(raw["volume"]),
    )


def write_dataset(path: Path, candles: Iterable[HistoricalCandle]) -> DatasetManifest:
    rows = tuple(candles)
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = tuple(HistoricalCandle.model_fields)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            payload = row.model_dump(mode="json")
            writer.writerow(payload)
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    return inspect_dataset(rows, digest)


def inspect_dataset(rows: tuple[HistoricalCandle, ...], digest: str = "") -> DatasetManifest:
    if not rows:
        raise ValueError("Historical dataset is empty")
    timestamps = [row.time for row in rows]
    duplicates = len(timestamps) - len(set(timestamps))
    invalid = sum(
        row.bid_low > min(row.bid_open, row.bid_close) or row.bid_high < max(row.bid_open, row.bid_close)
        or row.ask_low > min(row.ask_open, row.ask_close) or row.ask_high < max(row.ask_open, row.ask_close)
        for row in rows
    )
    negative = sum(row.spread_close < 0 for row in rows)
    gaps = sum(
        current.weekday() < 5 and current - previous > timedelta(minutes=5)
        for previous, current in zip(timestamps, timestamps[1:], strict=False)
    )
    spreads = sorted(row.spread_close for row in rows)
    median = spreads[len(spreads) // 2]
    years = len({row.time.year for row in rows})
    suitable = years >= 3 and not duplicates and not invalid and not negative
    return DatasetManifest(
        provider="OANDA_V20", instrument="XAU_USD", granularity="M5",
        start=min(timestamps), end=max(timestamps), rows=len(rows), calendar_years=years,
        duplicate_timestamps=duplicates, invalid_ohlc_rows=invalid,
        negative_spread_rows=negative, weekday_gaps_over_5_minutes=gaps,
        median_close_spread=median, sha256=digest, suitable_for_final_validation=suitable,
    )
