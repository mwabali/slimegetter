"""Continuously advance paper positions every five minutes."""
import time

from app.workers.run_simulation_once import run_once

while True:
    try:
        print(f"simulation_cycle: {run_once()}")
    except Exception as exc:
        print(f"simulation_cycle_error: {type(exc).__name__}: {exc}")
    time.sleep(300)
