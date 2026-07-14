# MT5 demo adapter safety contract

`MetaTrader5Gateway` runs only on a Windows worker with the MT5 terminal installed.

- `connect()` rejects every account that is not MT5 demo mode.
- No import or startup opens an MT5 connection; a worker must explicitly call `connect()`.
- Order submission requires all four gates: MT5 adapter order permission, disabled kill switch, `XAU_TRADING_MODE=demo`, and `XAU_EXECUTION_ENABLED=true`.
- Commander Erwin approval and a matching proposal ID are enforced before the gateway is called.
- Idempotency uses the proposal ID, so a retry returns the original ticket rather than opening a duplicate trade.

The current API does not instantiate this gateway. Wire it only in the dedicated Windows worker after completing demo soak tests.

For shadow mode, run `python -m app.workers.run_shadow_loop` from `backend`. It reads live MT5 data every five minutes and journals agent decisions; it has no execution-service import or order path.
