# Mission Control dashboard: current architecture

## Current flow

The Windows shadow worker reads MT5 prices, creates a typed decision preview, and writes five ordered journal events under one correlation ID. FastAPI exposes the timeline and an in-memory WebSocket heartbeat. The React shell renders only a placeholder chart and basic replay list.

## Dashboard contract gap

The original API was optimized for individual operations rather than dashboard reads. Phase 2 adds read-only contracts for platform status, agent state, current cycle, paginated journal events, and replay. All unavailable data is represented as `UNKNOWN`, never invented.

## Safety boundary

Dashboard endpoints are read-only. They do not import the execution service, alter MT5 settings, change risk configuration, or submit an order. `XAU_EXECUTION_ENABLED` remains the authority for execution permission.
