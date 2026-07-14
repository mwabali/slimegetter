# Phase 1: safety and auditability foundation

## Implemented

- Strict, typed trade-proposal and risk-decision contracts.
- Commander Erwin's deterministic checks for session, spread, trade count, exposure, risk, loss limits, margin, stop/take-profit direction, and reward-risk ratio.
- A disabled-by-default MT5 boundary. It cannot submit an order until a separately implemented, explicitly enabled demo adapter is supplied.
- Append-only journal tables for trade proposals and Commander Erwin's decisions, linked by a correlation ID.
- FastAPI documentation and a non-executing assessment endpoint.
- Annie, Mikasa, and Eren are now isolated rule-based services with a simulation-only routing workflow.

## Deliberately deferred

- MT5 connectivity and order placement.
- Armin and Levi implementations.
- External market-data and economic-calendar adapters. The new services only consume typed, sourced inputs.
- Authentication/authorization, which is required before exposing the API outside a development network.
- Live trading. This project remains demo-only by configuration and implementation.

## Operational rule

The assessment API is a development/simulation API. In the production orchestration path, the active risk profile must be loaded from a versioned, administrator-controlled configuration rather than client input.

The `/api/v1/simulation/decision-preview` endpoint deliberately cannot execute. It journals every agent outcome with one correlation ID, including waits and rejected trades, so the dashboard can replay the full decision path.
