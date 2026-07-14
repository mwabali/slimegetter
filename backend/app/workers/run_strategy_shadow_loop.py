import time

from app.workers.run_strategy_shadow_once import run_once

while True:
    try:
        print(f"strategy_shadow: {run_once()}")
    except Exception as exc:
        print(f"strategy_shadow_error: {type(exc).__name__}: {exc}")
    time.sleep(300)
