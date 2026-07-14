from datetime import UTC, datetime, timedelta

from app.agents.annie.models import AnnieAssessment, AnnieNewsReport, NewsArticle, NewsRiskStatus
from app.domain.market.models import EconomicEvent, EventImpact


class AnnieService:
    """Classifies sourced macro-event risk. It has no market or trade authority."""

    def assess(
        self,
        events: tuple[EconomicEvent, ...],
        source_freshness_minutes: int,
        now: datetime | None = None,
    ) -> AnnieAssessment:
        current_time = now or datetime.now(UTC)
        window_start = current_time - timedelta(minutes=60)
        window_end = current_time + timedelta(minutes=120)
        relevant = tuple(
            event
            for event in events
            if event.is_gold_relevant and window_start <= event.scheduled_at <= window_end
        )
        high_impact = tuple(event for event in relevant if event.impact is EventImpact.HIGH)
        medium_impact = tuple(event for event in relevant if event.impact is EventImpact.MEDIUM)
        if source_freshness_minutes > 30:
            return AnnieAssessment(
                status=NewsRiskStatus.HIGH_RISK,
                reasons=("External information is stale; fail closed",),
                relevant_events=relevant,
                source_freshness_minutes=source_freshness_minutes,
            )
        if high_impact:
            return AnnieAssessment(
                status=NewsRiskStatus.NEWS_EVENT,
                reasons=("High-impact gold-relevant event is inside the two-hours-before/one-hour-after lockout",),
                relevant_events=high_impact,
                source_freshness_minutes=source_freshness_minutes,
            )
        if medium_impact:
            return AnnieAssessment(
                status=NewsRiskStatus.MEDIUM_RISK,
                reasons=("Medium-impact gold-relevant event is approaching",),
                relevant_events=medium_impact,
                source_freshness_minutes=source_freshness_minutes,
            )
        return AnnieAssessment(
            status=NewsRiskStatus.SAFE,
            reasons=("No relevant scheduled event is within the configured lockout window",),
            source_freshness_minutes=source_freshness_minutes,
        )

    def assess_headlines(self, articles: tuple[NewsArticle, ...]) -> AnnieNewsReport:
        urgent_words = ("war", "attack", "sanction", "emergency", "fed", "inflation", "tariff")
        matched = [article for article in articles if any(word in article.title.lower() for word in urgent_words)]
        status = NewsRiskStatus.HIGH_RISK if matched else NewsRiskStatus.SAFE
        summary = f"{len(articles)} recent headlines found; {len(matched)} require human review."
        return AnnieNewsReport(status=status, summary=summary, articles=articles)
