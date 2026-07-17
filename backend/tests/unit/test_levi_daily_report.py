import subprocess
from datetime import UTC, date, datetime
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import create_engine
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.reporting.levi_daily_report import (
    SecretScanError,
    build_daily_report,
    publish_daily_report,
    sanitize,
    scan_for_secrets,
)
from app.infrastructure.persistence.models import (
    Base,
    ClosedTradeRecord,
    DecisionEventRecord,
    ExecutionIncidentRecord,
    WorkerHeartbeatRecord,
)


def session_with_report_data() -> Session:
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    session = Session(engine)
    correlation_id = uuid4()
    session.add_all(
        [
            DecisionEventRecord(
                correlation_id=correlation_id,
                event_sequence=1,
                agent_name="PIXIS",
                event_type="MARKET_CLOSED_COOLDOWN",
                payload_json='{"message":"cooldown","password":"remove-me"}',
            ),
            WorkerHeartbeatRecord(worker_name="demo-position-manager", status="ERROR", message="Pixis cooled down"),
            ExecutionIncidentRecord(
                incident_type="CLOSE_FAILED",
                severity="CRITICAL",
                position_ticket="ticket-1",
                message="Market closed cooldown active",
            ),
            ClosedTradeRecord(
                strategy_version="mt5-imported@1.0",
                session="NEW_YORK",
                pnl=1.25,
                reward_risk=0.5,
                source_deal_ticket="deal-1",
                closed_at=datetime.now(UTC),
            ),
        ]
    )
    session.commit()
    return session


def test_redaction_removes_sensitive_fields() -> None:
    payload = {"safe": 1, "password": "x", "nested": {"api_key": "abc", "value": 2}, "items": [{"token": "t", "ok": True}]}
    assert sanitize(payload) == {"safe": 1, "nested": {"value": 2}, "items": [{"ok": True}]}


def test_secret_detection_blocks_publication() -> None:
    with pytest.raises(SecretScanError):
        scan_for_secrets("authorization: Bearer abcdefghijklmnopqrstuvwxyz")


def test_report_publication_writes_daily_and_latest_files(tmp_path: Path) -> None:
    session = session_with_report_data()
    try:
        result = publish_daily_report(session, date.today(), tmp_path / "reports" / "daily", tmp_path, commit=False)
        assert result.changed is True
        assert result.json_path.exists()
        assert result.markdown_path.exists()
        assert (tmp_path / "reports" / "daily" / "latest.json").exists()
        assert "password" not in result.json_path.read_text(encoding="utf-8")
    finally:
        session.close()


def test_unchanged_report_produces_no_duplicate_commit(tmp_path: Path) -> None:
    session = session_with_report_data()
    calls: list[list[str]] = []

    def fake_git(args: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
        calls.append(args)
        return subprocess.CompletedProcess(["git", *args], 0, "", "")

    try:
        report_day = date.today()
        first = publish_daily_report(session, report_day, tmp_path / "reports" / "daily", tmp_path, commit=True, git_runner=fake_git)
        second = publish_daily_report(session, report_day, tmp_path / "reports" / "daily", tmp_path, commit=True, git_runner=fake_git)
        assert first.committed is True
        assert second.changed is False
        assert second.committed is False
        assert [call[0] for call in calls].count("commit") == 1
    finally:
        session.close()


def test_report_builder_does_not_import_trading_gateways() -> None:
    import sys

    session = session_with_report_data()
    try:
        sys.modules.pop("app.infrastructure.mt5.gateway", None)
        sys.modules.pop("app.application.execution", None)
        build_daily_report(session, date.today())
        assert "app.infrastructure.mt5.gateway" not in sys.modules
        assert "app.application.execution" not in sys.modules
    finally:
        session.close()


def test_github_failure_isolated_to_reporting(tmp_path: Path) -> None:
    session = session_with_report_data()

    def failing_git(args: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
        raise subprocess.CalledProcessError(128, ["git", *args], "github unavailable")

    try:
        with pytest.raises(subprocess.CalledProcessError):
            publish_daily_report(session, date.today(), tmp_path / "reports" / "daily", tmp_path, commit=True, git_runner=failing_git)
        assert session.scalar(select(func.count()).select_from(ExecutionIncidentRecord)) == 1
    finally:
        session.close()
