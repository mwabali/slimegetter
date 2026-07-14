"""Run from the Windows worker: python -m app.workers.run_shadow_loop."""
import time

from app.workers.run_shadow_once import run_once

while True:
    try:
        run_once()
    except Exception as exc:
        print(f"shadow_cycle_error: {exc}")
    time.sleep(300)
