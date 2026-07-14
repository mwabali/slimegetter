# XAUUSD Mission Control

Safety-first, explainable, demo-only trading platform foundation.

## Current milestone

- Commander Erwin deterministic risk assessment
- Immutable proposal/decision journal schema and Alembic migration
- Safe-by-default FastAPI API (`/api/v1/health`, `/api/v1/risk/assess`)
- Journaled, simulation-only agent chain (`/api/v1/simulation/decision-preview`) for Annie → Mikasa → Eren → Commander Erwin
- Ordered decision replay (`/api/v1/journal/timeline/{correlation_id}`)
- React Mission Control shell in `frontend/`, including timeline replay and status panels
- Demo-only execution boundary, mock broker, Armin analytics, backtesting gate, and Levi review adapter
- MT5 gateway boundary that is disabled by default
- Unit and integration tests

## Run locally on Windows

For normal use, double-click `Start Mission Control.cmd` in the project root.
It starts the API, dashboard and observation workers, then opens Mission Control
at `http://127.0.0.1:5173`. Double-click `Stop Mission Control.cmd` to stop only
the processes recorded by the launcher. Manual launches force execution off,
activate the kill switch and do not submit MT5 orders.

From `backend` with Python 3.13:

```powershell
py -3.13 -m venv .venv
.venv\Scripts\Activate.ps1
pip install -e ".[dev]"
alembic upgrade head
pytest
uvicorn app.main:app --reload
```

Interactive API documentation is available at `http://127.0.0.1:8000/docs`.

`XAU_EXECUTION_ENABLED` defaults to `false`; no MT5 order implementation is connected in this milestone.

The simulation endpoint cannot send orders, but it does persist every agent outcome under one correlation ID. Use the returned ID with the timeline endpoint to replay the decision process.

See [Windows VPS deployment](docs/windows-vps-deployment.md) for the demo deployment procedure.

Operational monitoring and soak drills are in [operations](docs/operations.md).

By default, Annie uses free official U.S. release-calendar data for high-impact BLS events. FMP is optional.

The real MT5 adapter contract is documented in [MT5 demo adapter](docs/mt5-demo-adapter.md). It is deliberately not wired into the API process.
