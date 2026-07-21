# Restored Avenger Session Controller

This branch adds the thin session layer requested around the recovered Sunday
Avenger/SlimeGetter behavior. It does not change bracket geometry, risk sizing,
position protection, or close logic.

Recovered operating windows, expressed in Africa/Nairobi time:

- `03:00-05:00 EAT`
- `16:00-22:00 EAT`

Outside those windows the entry worker records `COOLED_DOWN` and submits no
new order. The position manager remains independent so an existing protected
position can still be managed and reconciled.

For demo testing only, `XAU_DEMO_SESSION_OVERRIDE=true` authorizes the entry
worker outside those windows. It does not bypass demo mode, broker protection,
the one-position exposure gate, or risk checks. It must remain unset/false for
normal session testing and is never valid for live execution.

The report worker is separate from trading and uses only the journal database.
It writes `reports/session/YYYY-MM-DD-window.json` and `.md` summaries for
completed windows. Missing data is represented as `null`; the worker does not
invent holding time, floating P/L, or directional P/L.

Start it independently from the backend directory:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\start_session_report_worker.ps1
```

It has no MT5 gateway import and cannot submit orders, close positions, or
modify protection.
