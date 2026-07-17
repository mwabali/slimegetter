"""Continuously manage open MT5 demo positions."""
import time

from app.config.settings import get_settings
from app.domain.journal.repository import TradeJournalRepository
from app.infrastructure.persistence.database import SessionLocal
from app.workers.run_demo_position_manager_once import run_once


while True:
    try:
        print(f"demo_position_manager_cycle: {run_once()}")
    except Exception as exc:
        with SessionLocal() as session:
            TradeJournalRepository().record_heartbeat(session, "demo-position-manager", "ERROR", f"Position manager blocked: {type(exc).__name__}")
        print(f"demo_position_manager_blocked: {type(exc).__name__}: {exc}")
    time.sleep(get_settings().demo_position_poll_seconds)
