import json
import re
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Protocol
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from app.domain.market.models import EconomicEvent, EventImpact, MarketSnapshot


class MarketDataProvider(Protocol):
    """Adapters normalize vendor data; agents only see typed snapshots."""
    def latest_xauusd(self) -> MarketSnapshot: ...


class EconomicCalendarProvider(Protocol):
    def upcoming_gold_events(self) -> tuple[EconomicEvent, ...]: ...


class UnavailableMarketDataProvider:
    def latest_xauusd(self) -> MarketSnapshot:
        raise RuntimeError("No live market-data provider is configured")


class EmptyEconomicCalendarProvider:
    def upcoming_gold_events(self) -> tuple[EconomicEvent, ...]:
        return ()


class VerifiedManualCalendarProvider:
    """Source-linked, human-reviewed fallback that expires closed."""
    def __init__(self, path: str) -> None:
        self._path = Path(path)

    def upcoming_gold_events(self) -> tuple[EconomicEvent, ...]:
        payload = json.loads(self._path.read_text(encoding="utf-8"))
        verified_until = datetime.fromisoformat(payload["verified_until"].replace("Z", "+00:00"))
        if datetime.now(UTC) > verified_until:
            raise RuntimeError("Manual economic calendar verification has expired; fail closed")
        events = []
        for item in payload.get("events", []):
            events.append(EconomicEvent(
                title=item["title"],
                impact=EventImpact(item["impact"]),
                scheduled_at=datetime.fromisoformat(item["scheduled_at"].replace("Z", "+00:00")),
                source=item["source"],
                source_url=item.get("source_url"),
                is_gold_relevant=bool(item.get("is_gold_relevant", True)),
            ))
        return tuple(events)


class FmpEconomicCalendarProvider:
    """Source-traceable FMP economic calendar adapter for Annie's news blackout checks."""
    def __init__(self, api_key: str, timeout_seconds: int = 10) -> None:
        self._api_key, self._timeout_seconds = api_key, timeout_seconds

    def upcoming_gold_events(self) -> tuple[EconomicEvent, ...]:
        now = datetime.now(UTC)
        params = urlencode({"from": now.date().isoformat(), "to": (now + timedelta(days=2)).date().isoformat(), "apikey": self._api_key})
        with urlopen(f"https://financialmodelingprep.com/stable/economic-calendar?{params}", timeout=self._timeout_seconds) as response:
            records = json.loads(response.read().decode("utf-8"))
        events: list[EconomicEvent] = []
        for item in records:
            if item.get("country") not in {"US", "United States"}: continue
            impact = {"high": EventImpact.HIGH, "medium": EventImpact.MEDIUM}.get(str(item.get("impact", "low")).lower(), EventImpact.LOW)
            try: scheduled = datetime.fromisoformat(str(item["date"]).replace("Z", "+00:00"))
            except (KeyError, ValueError): continue
            if scheduled.tzinfo is None: scheduled = scheduled.replace(tzinfo=UTC)
            events.append(EconomicEvent(title=str(item.get("event", "Economic event")), impact=impact, scheduled_at=scheduled, source="Financial Modeling Prep", source_url="https://financialmodelingprep.com/stable/economic-calendar", is_gold_relevant=True))
        return tuple(events)


class FinnhubEconomicCalendarProvider:
    """Economic calendar adapter using Finnhub's application API."""
    def __init__(self, api_key: str, timeout_seconds: int = 10) -> None:
        self._api_key, self._timeout_seconds = api_key, timeout_seconds

    def upcoming_gold_events(self) -> tuple[EconomicEvent, ...]:
        now = datetime.now(UTC)
        query = urlencode({"from": now.date().isoformat(), "to": (now + timedelta(days=2)).date().isoformat(), "token": self._api_key})
        request = Request(f"https://finnhub.io/api/v1/calendar/economic?{query}", headers={"User-Agent": "XAUUSD-Mission-Control/0.1"})
        with urlopen(request, timeout=self._timeout_seconds) as response:
            payload = json.loads(response.read().decode("utf-8"))
        records = payload.get("economicCalendar", payload) if isinstance(payload, dict) else payload
        events: list[EconomicEvent] = []
        for item in records:
            if str(item.get("country", "")).upper() not in {"US", "UNITED STATES"}: continue
            name = str(item.get("event", item.get("name", "Economic event")))
            impact = EventImpact.HIGH if any(word in name.lower() for word in ("cpi", "employment", "nonfarm", "fed", "fomc", "interest rate", "ppi")) else EventImpact.MEDIUM
            raw_time = str(item.get("time", item.get("date", ""))).replace("Z", "+00:00")
            try: scheduled = datetime.fromisoformat(raw_time)
            except ValueError: continue
            if scheduled.tzinfo is None: scheduled = scheduled.replace(tzinfo=UTC)
            events.append(EconomicEvent(title=name, impact=impact, scheduled_at=scheduled, source="Finnhub", source_url="https://finnhub.io/docs/api/economic-calendar", is_gold_relevant=True))
        return tuple(events)


class OfficialUsCalendarProvider:
    """Free, source-traceable scheduled-risk feed using official BLS release calendar data."""
    _bls_icalendar = "https://www.bls.gov/schedule/news_release/bls.ics"
    _high_impact = ("consumer price index", "employment situation", "producer price index", "employment cost index")

    def __init__(self, timeout_seconds: int = 10) -> None:
        self._timeout_seconds = timeout_seconds

    def upcoming_gold_events(self) -> tuple[EconomicEvent, ...]:
        request = Request(self._bls_icalendar, headers={"User-Agent": "XAUUSD-Mission-Control/0.1 (demo research)"})
        with urlopen(request, timeout=self._timeout_seconds) as response:
            content = response.read().decode("utf-8", errors="replace")
        events: list[EconomicEvent] = []
        for block in content.split("BEGIN:VEVENT")[1:]:
            summary = self._value(block, "SUMMARY")
            timestamp = self._value(block, "DTSTART")
            if not summary or not timestamp: continue
            title = summary.lower()
            if not any(term in title for term in self._high_impact): continue
            scheduled = self._parse_icalendar_time(timestamp)
            if scheduled:
                events.append(EconomicEvent(title=summary, impact=EventImpact.HIGH, scheduled_at=scheduled, source="U.S. Bureau of Labor Statistics", source_url=self._bls_icalendar, is_gold_relevant=True))
        return tuple(events)

    @staticmethod
    def _value(block: str, key: str) -> str | None:
        match = re.search(rf"(?m)^{key}(?:;[^:]*)?:(.+)$", block)
        return match.group(1).strip() if match else None

    @staticmethod
    def _parse_icalendar_time(value: str) -> datetime | None:
        try:
            if value.endswith("Z"): return datetime.strptime(value, "%Y%m%dT%H%M%SZ").replace(tzinfo=UTC)
            return datetime.strptime(value[:15], "%Y%m%dT%H%M%S").replace(tzinfo=UTC)
        except ValueError: return None
