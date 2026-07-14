from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.application.workflows.decision_preview import DecisionPreviewWorkflow
from app.infrastructure.persistence.models import Base
from tests.unit.test_agent_workflow import account, market, profile
from app.domain.journal.repository import TradeJournalRepository


def test_persists_ordered_agent_timeline() -> None:
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    preview = DecisionPreviewWorkflow().run(market(), (), 0, account(), profile())
    with Session(engine) as session:
        repository = TradeJournalRepository()
        repository.record_preview(session, preview)
        timeline = repository.timeline(session, preview.correlation_id)
    assert [event.sequence for event in timeline] == [1, 2, 3, 4, 5]
    assert [event.agent_name for event in timeline] == ["ANNIE", "MIKASA", "EREN", "COMMANDER_ERWIN", "SYSTEM"]
    assert timeline[3].payload["status"] == "APPROVED"
