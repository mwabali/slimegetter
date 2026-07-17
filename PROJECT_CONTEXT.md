# Project Context

This workspace is the active trading platform project: XAUUSD Mission Control.

The intended direction is a safety-first, explainable trading system with:

- A React Mission Control dashboard for monitoring market state, agents, decisions, positions, and learning evidence.
- A FastAPI backend with typed contracts, SQLAlchemy persistence, Alembic migrations, and read-only dashboard APIs.
- A journal-first architecture where each agent decision is persisted under a correlation ID for replay and audit.
- A staged agent flow: Annie for information risk, Mikasa for market quality, Eren for trade proposals, Commander Erwin for deterministic risk control, Armin for learning/performance review, and Levi for optional AI-assisted research review.
- Execution disabled by default, guarded by explicit demo-mode configuration, kill-switch state, MT5 demo verification, and Commander Erwin approval.

The target reference repo link `https://github.com/gkhamati5033-blip/TradingBot.git` was not accessible during inspection, so comparisons against that target remain pending until the repo URL or access is fixed.

