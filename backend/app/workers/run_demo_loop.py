"""Guarded fast-rearm demo loop. Never use for a live account.

The Avenger strategy still decides whether a bracket is valid on each cycle.
The shorter poll only reduces the time spent waiting to re-arm after a broker
pending bracket expires or is cancelled; exposure and duplicate-submission
guards remain authoritative.
"""
import time

from app.domain.journal.repository import TradeJournalRepository
from app.infrastructure.persistence.database import SessionLocal
from app.config.settings import get_settings
from app.workers.run_demo_once import run_once


while True:
    cycle_started = time.perf_counter()
    try:
        result = run_once()
        duration_ms = round((time.perf_counter() - cycle_started) * 1000, 2)
        with SessionLocal() as session:
            TradeJournalRepository().record_heartbeat(
                session,
                "demo-worker",
                "HEALTHY",
                f"Avenger cycle result={result}; cycle_duration_ms={duration_ms}; poll_seconds={get_settings().demo_entry_poll_seconds}",
            )
        print(f"demo_cycle: {result} duration_ms={duration_ms}")
    except Exception as exc:
        with SessionLocal() as session:
            duration_ms = round((time.perf_counter() - cycle_started) * 1000, 2)
            TradeJournalRepository().record_heartbeat(session, "demo-worker", "ERROR", f"Demo cycle blocked: {type(exc).__name__}; cycle_duration_ms={duration_ms}")
        print(f"demo_cycle_blocked: {type(exc).__name__}: {exc}")
    time.sleep(get_settings().demo_entry_poll_seconds)
