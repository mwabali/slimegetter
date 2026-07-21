"""Read-only session metrics and Markdown/JSON report writing."""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from statistics import median
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.infrastructure.persistence.models import (
    ClosedTradeRecord,
    DecisionEventRecord,
    ExecutionIncidentRecord,
    FillRecord,
    WorkerHeartbeatRecord,
)


@dataclass(frozen=True)
class SessionBounds:
    key: str
    start: datetime
    end: datetime


def _utc(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=UTC)


def _within(value: datetime | None, bounds: SessionBounds) -> bool:
    return value is not None and bounds.start <= _utc(value) < bounds.end


def _pnl_metrics(pnls: list[float]) -> dict[str, Any]:
    wins = [value for value in pnls if value > 0]
    losses = [value for value in pnls if value < 0]
    running = 0.0
    peak = 0.0
    max_drawdown = 0.0
    for value in pnls:
        running += value
        peak = max(peak, running)
        max_drawdown = max(max_drawdown, peak - running)
    gross_profit = sum(wins)
    gross_loss = abs(sum(losses))
    return {
        "trade_count": len(pnls),
        "wins": len(wins),
        "losses": len(losses),
        "breakeven": len(pnls) - len(wins) - len(losses),
        "win_rate": len(wins) / len(pnls) if pnls else 0.0,
        "gross_profit": gross_profit,
        "gross_loss": gross_loss,
        "average_win": sum(wins) / len(wins) if wins else 0.0,
        "average_loss": sum(losses) / len(losses) if losses else 0.0,
        "largest_win": max(wins) if wins else 0.0,
        "largest_loss": min(losses) if losses else 0.0,
        "profit_factor": gross_profit / gross_loss if gross_loss else None,
        "expectancy": sum(pnls) / len(pnls) if pnls else 0.0,
        "maximum_drawdown": max_drawdown,
        "realized_pnl": sum(pnls),
    }


def build_session_report(
    session: Session,
    bounds: SessionBounds,
    *,
    actual_bot_start: datetime | None = None,
    actual_bot_stop: datetime | None = None,
    starting_balance: float | None = None,
    ending_balance: float | None = None,
    starting_equity: float | None = None,
    ending_equity: float | None = None,
    floating_samples: list[float] | None = None,
) -> dict[str, Any]:
    closed = [
        row for row in session.scalars(select(ClosedTradeRecord).order_by(ClosedTradeRecord.closed_at))
        if _within(row.closed_at, bounds)
    ]
    fills = [
        row for row in session.scalars(select(FillRecord).order_by(FillRecord.filled_at))
        if _within(row.filled_at, bounds)
    ]
    events = [
        row for row in session.scalars(select(DecisionEventRecord).order_by(DecisionEventRecord.created_at))
        if _within(row.created_at, bounds)
    ]
    incidents = [
        row for row in session.scalars(select(ExecutionIncidentRecord).order_by(ExecutionIncidentRecord.created_at))
        if _within(row.created_at, bounds)
    ]
    heartbeats = list(session.scalars(select(WorkerHeartbeatRecord)))
    pnls = [float(row.pnl) for row in closed]
    metrics = _pnl_metrics(pnls)
    exit_fills = {row.deal_ticket: row for row in fills if row.entry in {"OUT", "OUT_BY"}}
    side_pnl: dict[str, list[float]] = {"BUY": [], "SELL": []}
    for row in closed:
        fill = exit_fills.get(row.source_deal_ticket)
        if fill is not None:
            original_side = "SELL" if fill.side == "BUY" else "BUY"
            side_pnl[original_side].append(float(row.pnl))
    event_types = [row.event_type for row in events]
    incident_types = [row.incident_type for row in incidents]
    floating = floating_samples or []
    return {
        "window_key": bounds.key,
        "window_start": bounds.start.isoformat(),
        "window_end": bounds.end.isoformat(),
        "timezone": "Africa/Nairobi (EAT)",
        "actual_bot_start": actual_bot_start.isoformat() if actual_bot_start else None,
        "actual_bot_stop": actual_bot_stop.isoformat() if actual_bot_stop else None,
        "starting_balance": starting_balance,
        "ending_balance": ending_balance,
        "starting_equity": starting_equity,
        "ending_equity": ending_equity,
        **metrics,
        "maximum_floating_pnl": max(floating) if floating else None,
        "minimum_floating_pnl": min(floating) if floating else None,
        "buy_count": len(side_pnl["BUY"]),
        "buy_pnl": sum(side_pnl["BUY"]),
        "sell_count": len(side_pnl["SELL"]),
        "sell_pnl": sum(side_pnl["SELL"]),
        "hard_stop_count": sum(1 for row in closed if (row.exit_reason or "").upper().find("STOP") >= 0),
        "normal_close_count": sum(1 for row in closed if (row.exit_reason or "").upper().find("STOP") < 0),
        "average_holding_time_seconds": None,
        "median_holding_time_seconds": None,
        "maximum_favorable_excursion": max((float(row.max_favorable_excursion or 0) for row in closed), default=0.0),
        "maximum_adverse_excursion": min((float(row.max_adverse_excursion or 0) for row in closed), default=0.0),
        "profit_giveback": sum(float(row.profit_giveback or 0) for row in closed),
        "pending_brackets": event_types.count("AVENGER_BRACKET_SUBMITTED"),
        "brackets_filled": sum(1 for row in fills if row.entry == "IN"),
        "brackets_cancelled": event_types.count("AVENGER_OPPOSITE_PENDING_CANCELLED"),
        "execution_errors": sum(1 for value in incident_types if value.startswith("EXECUTION")),
        "reconciliation_errors": sum(1 for value in incident_types if "RECONCIL" in value),
        "close_errors": sum(1 for value in incident_types if "CLOSE" in value),
        "sl_modification_errors": sum(1 for value in incident_types if "SL" in value or "PROTECTION" in value),
        "worker_restarts": sum(1 for row in heartbeats if "restart" in row.message.lower()),
        "mt5_disconnects": sum(1 for value in incident_types if "DISCONNECT" in value),
        "source_event_count": len(events),
        "source_fill_count": len(fills),
        "notes": [
            "Metrics are read-only summaries from the journal and synchronized fills.",
            "Missing holding-time or floating-P/L samples are reported as null rather than guessed.",
            "Evaluate NET PROFIT, PROFIT FACTOR, EXPECTANCY, MAXIMUM DRAWDOWN, and HARD-STOP FREQUENCY together.",
        ],
    }


def write_session_report(report: dict[str, Any], output_root: Path) -> tuple[Path, Path]:
    output_root.mkdir(parents=True, exist_ok=True)
    date_key = str(report["window_start"])[:10]
    window_key = str(report["window_key"]).lower().replace(":", "-")
    stem = f"{date_key}-{window_key}"
    json_path = output_root / f"{stem}.json"
    markdown_path = output_root / f"{stem}.md"
    json_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    markdown = [
        f"# Session Report: {report['window_key']}",
        "",
        f"- Window: `{report['window_start']}` to `{report['window_end']}`",
        f"- Timezone: `{report['timezone']}`",
        f"- Net P/L: **{report['realized_pnl']:.2f}**",
        f"- Profit factor: **{report['profit_factor']}**",
        f"- Expectancy: **{report['expectancy']:.4f}**",
        f"- Maximum drawdown: **{report['maximum_drawdown']:.2f}**",
        f"- Hard stops: **{report['hard_stop_count']}**",
        "",
        "## Trade Summary",
        "",
        f"Trades: {report['trade_count']} | Wins: {report['wins']} | Losses: {report['losses']} | Breakeven: {report['breakeven']}",
        f"Gross profit: {report['gross_profit']:.2f} | Gross loss: {report['gross_loss']:.2f}",
        f"BUY: {report['buy_count']} trades / {report['buy_pnl']:.2f} | SELL: {report['sell_count']} trades / {report['sell_pnl']:.2f}",
        "",
        "## Data Quality",
        "",
        *[f"- {note}" for note in report["notes"]],
    ]
    markdown_path.write_text("\n".join(markdown) + "\n", encoding="utf-8")
    return json_path, markdown_path
