"""High-signal integrity audit for Mission Control persistence."""
from __future__ import annotations

import json
from collections import Counter, defaultdict
from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from app.infrastructure.persistence.database import SessionLocal
from app.infrastructure.persistence.models import (
    DecisionEventRecord, ExecutionAttemptRecord, SimulatedPositionRecord, WorkerHeartbeatRecord,
)


def main() -> None:
    findings: list[dict[str, object]] = []
    with SessionLocal() as session:
        events = tuple(session.scalars(select(DecisionEventRecord)).all())
        keys = [(str(row.correlation_id), row.event_sequence) for row in events]
        duplicates = sum(count - 1 for count in Counter(keys).values() if count > 1)
        malformed = 0
        timelines: dict[str, list[int]] = defaultdict(list)
        for row in events:
            timelines[str(row.correlation_id)].append(row.event_sequence)
            try: json.loads(row.payload_json)
            except json.JSONDecodeError: malformed += 1
        noncontiguous = sum(1 for values in timelines.values() if sorted(values) != list(range(1, max(values) + 1)))
        findings.extend((
            {"check": "decision key uniqueness", "failures": duplicates, "severity": "CRITICAL"},
            {"check": "decision payload JSON validity", "failures": malformed, "severity": "HIGH"},
            {"check": "replay sequence continuity", "failures": noncontiguous, "severity": "HIGH"},
        ))

        simulations = tuple(session.scalars(select(SimulatedPositionRecord)).all())
        invalid_simulations = sum(1 for row in simulations if (
            row.status not in {"OPEN", "CLOSED"}
            or (row.status == "OPEN" and (row.closed_at is not None or row.exit_price is not None or row.pnl is not None))
            or (row.status == "CLOSED" and (row.closed_at is None or row.exit_price is None or row.pnl is None or not row.close_reason))
        ))
        findings.append({"check": "paper lifecycle consistency", "failures": invalid_simulations, "severity": "HIGH"})

        attempts = tuple(session.scalars(select(ExecutionAttemptRecord)).all())
        invalid_attempts = sum(1 for row in attempts if row.status not in {"CLAIMED", "SUBMITTED", "UNKNOWN_RECONCILE"} or (row.status == "SUBMITTED" and not row.broker_ticket))
        findings.append({"check": "execution claim consistency", "failures": invalid_attempts, "severity": "CRITICAL"})

        now = datetime.now(UTC); required = {"shadow-worker", "strategy-shadow-worker", "simulation-worker"}
        heartbeats = {row.worker_name: row for row in session.scalars(select(WorkerHeartbeatRecord)).all()}
        stale = 0
        for name in required:
            row = heartbeats.get(name)
            if row is None: stale += 1; continue
            seen = row.last_seen_at if row.last_seen_at.tzinfo else row.last_seen_at.replace(tzinfo=UTC)
            if row.status != "HEALTHY" or now - seen > timedelta(minutes=15): stale += 1
        findings.append({"check": "required worker freshness", "failures": stale, "severity": "HIGH"})

    failed = [row for row in findings if row["failures"]]
    result = {"passed": not failed, "checked_at": datetime.now(UTC).isoformat(), "counts": {"decision_events": len(events), "cycles": len(timelines), "paper_positions": len(simulations), "execution_attempts": len(attempts)}, "findings": findings}
    print(json.dumps(result, indent=2))
    if failed: raise SystemExit(1)


if __name__ == "__main__": main()
