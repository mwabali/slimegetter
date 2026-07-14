# Operations and soak testing

Run 20 demo sessions with execution disabled, then 20 sessions at broker-minimum volume. Review all journal timelines daily.

Drill the kill switch, duplicate proposal retry, stale provider failure, database disconnect, and daily/weekly loss-limit rejections. Back up PostgreSQL daily to encrypted off-host storage. Alert on API failures, stale data, MT5 disconnects, database errors, risk rejections, and execution attempts while disabled.
# Guarded demo trading

The demo worker is fail-closed and refuses to start unless all three gates are
set explicitly:

```powershell
$env:XAU_EXECUTION_ENABLED="true"
$env:XAU_DEMO_TRADING_CONFIRMED="true"
$env:XAU_KILL_SWITCH_ACTIVE="false"
python -m app.workers.run_demo_loop
```

Do not set these values until the backend tests pass, the MT5 terminal is logged
into a demo account, Annie's calendar query succeeds, market data is fresh, and
the dashboard reports no degraded safety service. The worker rechecks the demo
account, sizes against the broker's XAUUSD contract specification, reruns
Commander Erwin, and permits at most one open position. Any failed check records
or reports `NO_ORDER`; it must never be bypassed to force a trade.

Emergency stop:

```powershell
$env:XAU_KILL_SWITCH_ACTIVE="true"
```

Stop the worker process as well. The kill switch blocks new orders; it does not
silently close an existing position.
