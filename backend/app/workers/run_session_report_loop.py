"""Separate read-only session report worker; it has no MT5 execution path."""
from __future__ import annotations

import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

from app.application.session_controller import HISTORICAL_WINDOWS, EAT
from app.application.session_reports import SessionBounds, build_session_report, write_session_report
from app.infrastructure.persistence.database import SessionLocal


def completed_windows(now_utc: datetime) -> list[SessionBounds]:
    local = now_utc.astimezone(EAT)
    output: list[SessionBounds] = []
    for day_offset in (0, -1):
        date = local.date() + timedelta(days=day_offset)
        for window in HISTORICAL_WINDOWS:
            start_local = datetime.combine(date, window.start, EAT)
            end_local = datetime.combine(date, window.end, EAT)
            if end_local.astimezone(UTC) < now_utc:
                output.append(SessionBounds(window.key, start_local.astimezone(UTC), end_local.astimezone(UTC)))
    return output


def generate_completed_reports(now_utc: datetime | None = None) -> list[Path]:
    current = (now_utc or datetime.now(UTC)).astimezone(UTC)
    root = Path(__file__).resolve().parents[2] / "reports" / "session"
    generated: list[Path] = []
    for bounds in completed_windows(current):
        with SessionLocal() as session:
            report = build_session_report(session, bounds, actual_bot_stop=bounds.end)
        json_path, _ = write_session_report(report, root)
        generated.append(json_path)
    return generated


while True:
    try:
        print({"session_reports": [str(path) for path in generate_completed_reports()]}, flush=True)
    except Exception as exc:
        print(f"session_report_failed: {type(exc).__name__}: {exc}", flush=True)
    time.sleep(300)
