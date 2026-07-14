from datetime import UTC, datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

from app.domain.market.models import EconomicEvent


class NewsRiskStatus(StrEnum):
    SAFE = "SAFE"
    MEDIUM_RISK = "MEDIUM_RISK"
    HIGH_RISK = "HIGH_RISK"
    NEWS_EVENT = "NEWS_EVENT"


class AnnieAssessment(BaseModel):
    model_config = ConfigDict(frozen=True)

    status: NewsRiskStatus
    reasons: tuple[str, ...] = Field(min_length=1)
    relevant_events: tuple[EconomicEvent, ...] = ()
    source_freshness_minutes: int = Field(ge=0)
    assessed_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class NewsArticle(BaseModel):
    model_config = ConfigDict(frozen=True)
    title: str
    url: str
    publisher: str | None = None
    published_at: datetime | None = None


class AnnieNewsReport(BaseModel):
    model_config = ConfigDict(frozen=True)
    status: NewsRiskStatus
    summary: str
    articles: tuple[NewsArticle, ...]
    disclaimer: str = "News headlines are research evidence, not trade instructions."
