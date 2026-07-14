"""Guarded five-minute demo loop. Never use for a live account."""
import time

from app.domain.journal.repository import TradeJournalRepository
from app.infrastructure.persistence.database import SessionLocal
from app.workers.run_demo_once import run_once


while True:
    try:
        print(f"demo_cycle: {run_once()}")
    except Exception as exc:
        with SessionLocal() as session:
            TradeJournalRepository().record_heartbeat(session, "demo-worker", "ERROR", f"Demo cycle blocked: {type(exc).__name__}")
        print(f"demo_cycle_blocked: {type(exc).__name__}: {exc}")
    time.sleep(300)
