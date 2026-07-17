"""Publish sanitized daily Levi research reports.

This module is intentionally read-only with respect to trading.  It imports
database models and git/file utilities only: no MT5 gateway, execution service,
or position-management side effects.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
from collections import Counter
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path
from typing import Any, Callable

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config.settings import get_settings
from app.infrastructure.persistence.database import SessionLocal
from app.infrastructure.persistence.models import (
    ClosedTradeRecord,
    DecisionEventRecord,
    ExecutionIncidentRecord,
    ResearchProposalRecord,
    WorkerHeartbeatRecord,
)

SENSITIVE_FIELD_PATTERNS = (
    "password",
    "secret",
    "token",
    "api_key",
    "apikey",
    "login",
    "account_number",
    "accountnumber",
    "authorization",
    "credential",
)
SECRET_PATTERNS = (
    re.compile(r"(?i)\b(password|secret|token|api[_-]?key|authorization|credential)\b\s*[:=]"),
    re.compile(r"\bsk-[A-Za-z0-9_-]{20,}\b"),
    re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._-]{20,}\b"),
    re.compile(r"(?i)\bOPENAI_API_KEY\b"),
)
MAX_EVENTS = 100
MAX_INCIDENTS = 50
MAX_RESEARCH = 50


class SecretScanError(RuntimeError):
    pass


@dataclass(frozen=True)
class PublishResult:
    report_date: date
    changed: bool
    committed: bool
    json_path: Path
    markdown_path: Path


def report_date_after_cutoff(now: datetime, cutoff_hour_utc: int) -> date:
    observed = now if now.tzinfo else now.replace(tzinfo=UTC)
    observed = observed.astimezone(UTC)
    cutoff = datetime.combine(observed.date(), time(cutoff_hour_utc, tzinfo=UTC))
    return observed.date() if observed >= cutoff else observed.date() - timedelta(days=1)


def _is_sensitive_key(key: object) -> bool:
    normalized = re.sub(r"[^a-z0-9_]", "", str(key).lower())
    return any(pattern in normalized for pattern in SENSITIVE_FIELD_PATTERNS)


def sanitize(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): sanitize(raw) for key, raw in value.items() if not _is_sensitive_key(key)}
    if isinstance(value, (list, tuple)):
        return [sanitize(item) for item in value]
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    return value


def scan_for_secrets(text: str) -> None:
    for pattern in SECRET_PATTERNS:
        if pattern.search(text):
            raise SecretScanError("Possible credential detected in Levi report output")


def _safe_json(payload: str) -> dict[str, Any]:
    try:
        loaded = json.loads(payload)
    except json.JSONDecodeError:
        return {"unparseable_payload": True}
    return sanitize(loaded) if isinstance(loaded, dict) else {"payload": sanitize(loaded)}


def _day_bounds(report_day: date) -> tuple[datetime, datetime]:
    start = datetime.combine(report_day, time(0, 0), UTC)
    return start, start + timedelta(days=1)


def build_daily_report(session: Session, report_day: date) -> dict[str, Any]:
    start, end = _day_bounds(report_day)
    events = tuple(
        session.scalars(
            select(DecisionEventRecord)
            .where(DecisionEventRecord.created_at >= start, DecisionEventRecord.created_at < end)
            .order_by(DecisionEventRecord.created_at.desc(), DecisionEventRecord.event_sequence.desc())
            .limit(MAX_EVENTS)
        )
    )
    closed = tuple(
        session.scalars(
            select(ClosedTradeRecord)
            .where(ClosedTradeRecord.closed_at >= start, ClosedTradeRecord.closed_at < end)
            .order_by(ClosedTradeRecord.closed_at.desc())
        )
    )
    incidents = tuple(
        session.scalars(
            select(ExecutionIncidentRecord)
            .where(ExecutionIncidentRecord.created_at >= start, ExecutionIncidentRecord.created_at < end)
            .order_by(ExecutionIncidentRecord.created_at.desc())
            .limit(MAX_INCIDENTS)
        )
    )
    research = tuple(
        session.scalars(
            select(ResearchProposalRecord)
            .where(ResearchProposalRecord.created_at >= start, ResearchProposalRecord.created_at < end)
            .order_by(ResearchProposalRecord.created_at.desc())
            .limit(MAX_RESEARCH)
        )
    )
    heartbeats = tuple(session.scalars(select(WorkerHeartbeatRecord).order_by(WorkerHeartbeatRecord.worker_name)))
    event_counts = Counter(f"{event.agent_name}.{event.event_type}" for event in events)
    pnl = sum(float(row.pnl) for row in closed)
    report = {
        "report_date": report_day.isoformat(),
        "generated_at": end.isoformat(),
        "read_only_guarantee": {
            "trading_order_submission": False,
            "position_closure": False,
            "sltp_modification": False,
            "strategy_setting_modification": False,
            "incident_resolution": False,
        },
        "summary": {
            "decision_events_reviewed": len(events),
            "closed_trades": len(closed),
            "realized_pnl": round(pnl, 2),
            "unresolved_critical_incidents": sum(1 for row in incidents if row.severity == "CRITICAL" and row.resolved_at is None),
            "research_items": len(research),
        },
        "event_counts": dict(sorted(event_counts.items())),
        "closed_trades": [
            sanitize(
                {
                    "strategy_version": row.strategy_version,
                    "session": row.session,
                    "pnl": float(row.pnl),
                    "reward_risk": float(row.reward_risk),
                    "exit_reason": row.exit_reason,
                    "initial_risk_usd": float(row.initial_risk_usd) if row.initial_risk_usd is not None else None,
                    "exit_r": float(row.exit_r) if row.exit_r is not None else None,
                    "peak_r": float(row.peak_r) if row.peak_r is not None else None,
                    "closed_at": row.closed_at,
                }
            )
            for row in closed
        ],
        "recent_decisions": [
            sanitize(
                {
                    "timestamp": event.created_at,
                    "agent": event.agent_name,
                    "event_type": event.event_type,
                    "payload": _safe_json(event.payload_json),
                }
            )
            for event in events[:25]
        ],
        "health": [
            sanitize(
                {
                    "worker": row.worker_name,
                    "status": row.status,
                    "message": row.message,
                    "last_seen_at": row.last_seen_at,
                }
            )
            for row in heartbeats
        ],
        "incidents": [
            sanitize(
                {
                    "incident_type": row.incident_type,
                    "severity": row.severity,
                    "position_ticket": row.position_ticket,
                    "message": row.message,
                    "created_at": row.created_at,
                    "resolved_at": row.resolved_at,
                }
            )
            for row in incidents
        ],
        "levi_research": [
            sanitize(
                {
                    "title": row.title,
                    "summary": row.summary,
                    "status": row.status,
                    "created_at": row.created_at,
                }
            )
            for row in research
        ],
    }
    return sanitize(report)


def render_markdown(report: dict[str, Any]) -> str:
    summary = report["summary"]
    lines = [
        f"# Levi Daily Research Report - {report['report_date']}",
        "",
        "## Summary",
        f"- Decision events reviewed: {summary['decision_events_reviewed']}",
        f"- Closed trades: {summary['closed_trades']}",
        f"- Realized P/L: {summary['realized_pnl']}",
        f"- Unresolved critical incidents created today: {summary['unresolved_critical_incidents']}",
        f"- Levi research items: {summary['research_items']}",
        "",
        "## Event Counts",
    ]
    event_counts = report.get("event_counts", {})
    if event_counts:
        lines.extend(f"- {key}: {value}" for key, value in event_counts.items())
    else:
        lines.append("- No journal events recorded for this report day.")
    lines.extend(["", "## Incidents"])
    incidents = report.get("incidents", [])
    if incidents:
        lines.extend(f"- {row['severity']} {row['incident_type']}: {row['message']}" for row in incidents)
    else:
        lines.append("- No execution incidents created for this report day.")
    lines.extend(["", "## Closed Trades"])
    trades = report.get("closed_trades", [])
    if trades:
        lines.extend(f"- {row['strategy_version']} {row['session']}: P/L {row['pnl']} R:R {row['reward_risk']}" for row in trades)
    else:
        lines.append("- No closed trades recorded for this report day.")
    lines.extend(["", "## Read-Only Guarantee", "This report job does not submit orders, close positions, modify SL/TP, modify strategy settings, or resolve incidents.", ""])
    return "\n".join(lines)


def _write_if_changed(path: Path, content: str) -> bool:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and path.read_text(encoding="utf-8") == content:
        return False
    path.write_text(content, encoding="utf-8")
    return True


def write_report_files(report: dict[str, Any], output_root: Path) -> tuple[bool, Path, Path]:
    report_day = date.fromisoformat(str(report["report_date"]))
    json_text = json.dumps(report, indent=2, sort_keys=True) + "\n"
    markdown_text = render_markdown(report)
    scan_for_secrets(json_text)
    scan_for_secrets(markdown_text)
    dated_json = output_root / f"{report_day}.json"
    dated_md = output_root / f"{report_day}.md"
    changed = False
    changed |= _write_if_changed(dated_json, json_text)
    changed |= _write_if_changed(dated_md, markdown_text)
    changed |= _write_if_changed(output_root / "latest.json", json_text)
    changed |= _write_if_changed(output_root / "latest.md", markdown_text)
    return changed, dated_json, dated_md


def _run_git(args: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["git", *args], cwd=cwd, text=True, capture_output=True, check=True)


def publish_daily_report(
    session: Session,
    report_day: date,
    output_root: Path,
    repo_root: Path,
    commit: bool = False,
    git_runner: Callable[[list[str], Path], subprocess.CompletedProcess[str]] = _run_git,
) -> PublishResult:
    report = build_daily_report(session, report_day)
    changed, json_path, markdown_path = write_report_files(report, output_root)
    committed = False
    if changed and commit:
        relative_paths = [
            str(json_path.relative_to(repo_root)),
            str(markdown_path.relative_to(repo_root)),
            str((output_root / "latest.json").relative_to(repo_root)),
            str((output_root / "latest.md").relative_to(repo_root)),
        ]
        git_runner(["add", *relative_paths], repo_root)
        git_runner(["commit", "-m", f"research: publish Levi report for {report_day.isoformat()}"], repo_root)
        committed = True
    return PublishResult(report_day, changed, committed, json_path, markdown_path)


def main(argv: list[str] | None = None) -> int:
    settings = get_settings()
    parser = argparse.ArgumentParser(description="Publish sanitized daily Levi research report")
    parser.add_argument("--date", dest="report_date", help="Report date in YYYY-MM-DD")
    parser.add_argument("--output-root", default=str(Path("..") / "reports" / "daily"))
    parser.add_argument("--repo-root", default=str(Path("..").resolve()))
    parser.add_argument("--commit", action="store_true")
    args = parser.parse_args(argv)
    now = datetime.now(UTC)
    report_day = date.fromisoformat(args.report_date) if args.report_date else report_date_after_cutoff(now, settings.levi_daily_report_cutoff_hour_utc)
    with SessionLocal() as session:
        result = publish_daily_report(
            session=session,
            report_day=report_day,
            output_root=Path(args.output_root),
            repo_root=Path(args.repo_root),
            commit=args.commit,
        )
    print(json.dumps({"date": result.report_date.isoformat(), "changed": result.changed, "committed": result.committed, "json": str(result.json_path), "markdown": str(result.markdown_path)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
