# Windows VPS demo deployment

1. Install Python 3.13, Docker Desktop, MetaTrader 5, and the broker's XAUUSD demo terminal.
2. Run PostgreSQL and the API with `docker compose up -d --build`; apply `alembic upgrade head` from the API container.
3. Run the MT5 adapter as a separate Windows service under the demo terminal user. Keep `XAU_TRADING_MODE=demo` and `XAU_EXECUTION_ENABLED=false` during soak testing.
4. Store secrets only in `backend/.env`; restrict the file ACL to the service account. Never commit it.
5. Add a daily PostgreSQL backup, off-host backup copy, health monitoring, and alerts for stale market data, rejected orders, and drawdown limits.
6. Before enabling demo order submission, test the kill switch, duplicate idempotency key, disconnect recovery, and all Commander Erwin rejection conditions.

Live trading is intentionally not part of this deployment procedure. It requires a separate human-approved release and configuration review.
