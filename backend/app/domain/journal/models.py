from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class DecisionTimelineEvent(BaseModel):
    """Read model for replaying a correlated decision path in Mission Control."""

    model_config = ConfigDict(frozen=True)

    correlation_id: UUID
    sequence: int
    agent_name: str
    event_type: str
    payload: dict[str, Any]
    created_at: datetime | None
