import json
from datetime import UTC, datetime
from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.domain.journal.models import DecisionTimelineEvent
from app.domain.dashboard.models import CycleDashboardSummary, JournalListItem, JournalPage
from app.domain.trading.models import RiskDecision, TradeProposal
from app.infrastructure.persistence.models import DecisionEventRecord, TradeProposalRecord, WorkerHeartbeatRecord

if TYPE_CHECKING:
    from app.application.workflows.decision_preview import DecisionPreview


class TradeJournalRepository:
    """Append-only writer for decision evidence used in trade replay and audit."""

    def record_assessment(
        self, session: Session, proposal: TradeProposal, decision: RiskDecision
    ) -> None:
        with session.begin():
            self._record_proposal(session, proposal, decision.status.value)
            self._add_event(session, proposal.correlation_id, 1, "COMMANDER_ERWIN", "RISK_DECISION", decision.model_dump_json(), proposal.id)

    def record_preview(self, session: Session, preview: "DecisionPreview") -> None:
        """Persist every agent outcome, including waits and rejected proposals."""
        with session.begin():
            self._add_event(session, preview.correlation_id, 1, "ANNIE", "INFORMATION_RISK", preview.annie.model_dump_json())
            self._add_event(session, preview.correlation_id, 2, "MIKASA", "MARKET_QUALITY", preview.mikasa.model_dump_json())
            if preview.eren is None:
                self._add_event(session, preview.correlation_id, 3, "EREN", "NO_PROPOSAL", json.dumps({"reason": preview.final_message}))
            else:
                status = preview.erwin.status.value if preview.erwin else "CREATED"
                self._record_proposal(session, preview.eren, status)
                self._add_event(session, preview.correlation_id, 3, "EREN", "TRADE_PROPOSAL", preview.eren.model_dump_json(), preview.eren.id)
            if preview.erwin is None:
                self._add_event(session, preview.correlation_id, 4, "COMMANDER_ERWIN", "NOT_EVALUATED", json.dumps({"reason": preview.final_message}))
            else:
                self._add_event(session, preview.correlation_id, 4, "COMMANDER_ERWIN", "RISK_DECISION", preview.erwin.model_dump_json(), preview.erwin.proposal_id)
            self._add_event(session, preview.correlation_id, 5, "SYSTEM", "WORKFLOW_COMPLETED", json.dumps({"message": preview.final_message}))

    def record_collective_events(self, session: Session, correlation_id: UUID, events: tuple[tuple[int, str, str, str], ...]) -> None:
        """Append post-decision research/performance events to the same correlation."""
        with session.begin():
            for sequence, agent_name, event_type, payload_json in events:
                self._add_event(session, correlation_id, sequence, agent_name, event_type, payload_json)

    def append_event(self, session: Session, correlation_id: UUID, agent_name: str, event_type: str, payload: dict) -> int:
        """Append after the immutable timeline without overwriting fixed workflow steps."""
        latest = session.scalar(select(func.max(DecisionEventRecord.event_sequence)).where(DecisionEventRecord.correlation_id == correlation_id)) or 0
        sequence = int(latest) + 1
        self._add_event(session, correlation_id, sequence, agent_name, event_type, json.dumps(payload))
        session.commit()
        return sequence

    def timeline(self, session: Session, correlation_id: UUID) -> list[DecisionTimelineEvent]:
        statement = (
            select(DecisionEventRecord)
            .where(DecisionEventRecord.correlation_id == correlation_id)
            .order_by(DecisionEventRecord.event_sequence)
        )
        return [
            DecisionTimelineEvent(
                correlation_id=event.correlation_id,
                sequence=event.event_sequence,
                agent_name=event.agent_name,
                event_type=event.event_type,
                payload=json.loads(event.payload_json),
                created_at=event.created_at,
            )
            for event in session.scalars(statement)
        ]

    def latest_cycle(self, session: Session) -> CycleDashboardSummary | None:
        event = session.scalar(select(DecisionEventRecord).where(DecisionEventRecord.agent_name == "SYSTEM", DecisionEventRecord.event_type == "WORKFLOW_COMPLETED").order_by(DecisionEventRecord.created_at.desc()).limit(1))
        if event is None: return None
        count = session.scalar(select(func.count()).select_from(DecisionEventRecord).where(DecisionEventRecord.correlation_id == event.correlation_id)) or 0
        return CycleDashboardSummary(correlation_id=event.correlation_id, completed_at=event.created_at, final_message=json.loads(event.payload_json).get("message"), event_count=count)

    def journal_page(self, session: Session, offset: int, limit: int, agent: str | None = None, correlation_id: UUID | None = None) -> JournalPage:
        statement = select(DecisionEventRecord)
        if agent: statement = statement.where(DecisionEventRecord.agent_name == agent)
        if correlation_id: statement = statement.where(DecisionEventRecord.correlation_id == correlation_id)
        total = session.scalar(select(func.count()).select_from(statement.subquery())) or 0
        rows = session.scalars(statement.order_by(DecisionEventRecord.created_at.desc(), DecisionEventRecord.event_sequence.desc()).offset(offset).limit(limit))
        return JournalPage(items=tuple(JournalListItem(correlation_id=row.correlation_id, sequence=row.event_sequence, timestamp=row.created_at, bot=row.agent_name, event_type=row.event_type, payload=json.loads(row.payload_json)) for row in rows), offset=offset, limit=limit, total=total)

    def record_heartbeat(self, session: Session, worker_name: str, status: str, message: str) -> None:
        heartbeat = session.scalar(select(WorkerHeartbeatRecord).where(WorkerHeartbeatRecord.worker_name == worker_name).limit(1))
        if heartbeat is None:
            heartbeat = WorkerHeartbeatRecord(worker_name=worker_name, status=status, message=message)
            session.add(heartbeat)
        else:
            heartbeat.status = status
            heartbeat.message = message
            heartbeat.last_seen_at = datetime.now(UTC)
        session.commit()

    def latest_heartbeat(self, session: Session, worker_name: str) -> WorkerHeartbeatRecord | None:
        return session.scalar(select(WorkerHeartbeatRecord).where(WorkerHeartbeatRecord.worker_name == worker_name).order_by(WorkerHeartbeatRecord.last_seen_at.desc()).limit(1))

    @staticmethod
    def _record_proposal(session: Session, proposal: TradeProposal, status: str) -> None:
        session.add(TradeProposalRecord(id=proposal.id, correlation_id=proposal.correlation_id, symbol=proposal.symbol, side=proposal.side.value, status=status, confidence=proposal.confidence, reasoning=json.dumps({"reasons": proposal.reasons, "indicators": proposal.indicators_used})))

    @staticmethod
    def _add_event(session: Session, correlation_id: UUID, sequence: int, agent_name: str, event_type: str, payload_json: str, proposal_id: UUID | None = None) -> None:
        session.add(DecisionEventRecord(correlation_id=correlation_id, event_sequence=sequence, proposal_id=proposal_id, agent_name=agent_name, event_type=event_type, payload_json=payload_json))
