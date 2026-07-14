import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from sqlalchemy import select

from app.agents.armin.service import ArminService, TradeOutcome
from app.agents.mikasa.models import SimilarMarketPerformance
from app.agents.levi.service import LeviService
from app.config.settings import get_settings
from app.domain.trading.models import RiskProfile
from app.infrastructure.persistence.models import ClosedTradeRecord, ResearchProposalRecord
from app.infrastructure.mt5.gateway import MetaTrader5Gateway
from app.infrastructure.persistence.database import SessionLocal
from app.domain.journal.repository import TradeJournalRepository
from app.workers.shadow_mode import ShadowModeRunner
from app.infrastructure.market_data.factory import build_economic_calendar_provider


def _collective_events(session, correlation_id, final_message: str, start_sequence: int = 6) -> tuple[tuple[int, str, str, str], ...]:
    records = tuple(session.scalars(select(ClosedTradeRecord).order_by(ClosedTradeRecord.closed_at)).all())
    trades = tuple(TradeOutcome(strategy_version=row.strategy_version, session=row.session, pnl=Decimal(str(row.pnl)), reward_risk=Decimal(str(row.reward_risk))) for row in records)
    performance = ArminService().analyze(trades)
    events: list[tuple[int, str, str, str]] = [(start_sequence, "ARMIN", "PERFORMANCE_REPORT", performance.model_dump_json())]
    settings = get_settings()
    now = datetime.now(UTC)
    latest_research = session.scalar(select(ResearchProposalRecord).order_by(ResearchProposalRecord.created_at.desc()).limit(1))
    last_review = latest_research.created_at if latest_research else None
    if last_review and last_review.tzinfo is None:
        last_review = last_review.replace(tzinfo=UTC)
    due = last_review is None or now - last_review >= timedelta(minutes=settings.levi_min_interval_minutes)
    if not settings.levi_enabled:
        events.append((start_sequence + 1, "CPT_LEVI", "RESEARCH_DISABLED", json.dumps({"reason": "Levi is disabled by configuration"})))
    elif not due:
        events.append((start_sequence + 1, "CPT_LEVI", "RESEARCH_COOLDOWN", json.dumps({"next_review_after_minutes": settings.levi_min_interval_minutes})))
    else:
        context = json.dumps({"final_message": final_message, "closed_trade_count": len(trades), "performance": performance.model_dump(mode="json")})
        try:
            review = LeviService(settings.openai_model, settings.openai_api_key).review(context)
            session.add(ResearchProposalRecord(title="Levi journal review", summary=review.summary, citations_json=json.dumps(review.citations), status="REVIEWED"))
            for experiment in review.experiments:
                session.add(ResearchProposalRecord(title=experiment[:255], summary=review.summary, citations_json=json.dumps(review.citations), status="PROPOSED"))
            session.commit()
            events.append((start_sequence + 1, "CPT_LEVI", "RESEARCH_REVIEW", review.model_dump_json()))
        except Exception as exc:
            session.add(ResearchProposalRecord(title="Levi review unavailable", summary="Review unavailable; no strategy changes made", citations_json="[]", status="ERROR"))
            session.commit()
            events.append((start_sequence + 1, "CPT_LEVI", "RESEARCH_ERROR", json.dumps({"error": type(exc).__name__, "message": "Review unavailable; no strategy changes made"})))
    events.append((start_sequence + 2, "SYSTEM", "COLLECTIVE_COMPLETED", json.dumps({"message": "All advisory agents completed", "armin_trade_count": len(trades)})))
    return tuple(events)


def _similar_session_performance(session, market_session: str = "LONDON") -> SimilarMarketPerformance:
    """Summarize closed outcomes available for Mikasa's current session memory."""
    records = tuple(session.scalars(
        select(ClosedTradeRecord)
        .where(ClosedTradeRecord.session == market_session)
        .order_by(ClosedTradeRecord.closed_at.desc())
        .limit(100)
    ).all())
    if not records:
        return SimilarMarketPerformance(similarity_basis=f"SESSION:{market_session}")
    wins = sum(1 for row in records if Decimal(str(row.pnl)) > 0)
    return SimilarMarketPerformance(
        sample_size=len(records),
        win_rate=Decimal(wins) / Decimal(len(records)),
        average_reward_risk=sum((Decimal(str(row.reward_risk)) for row in records), Decimal("0")) / Decimal(len(records)),
        net_pnl=sum((Decimal(str(row.pnl)) for row in records), Decimal("0")),
        similarity_basis=f"SESSION:{market_session};LAST_100",
    )


def run_once() -> None:
    settings = get_settings()
    profile = RiskProfile(
        risk_per_trade_pct=str(settings.max_risk_per_trade_pct),
        max_daily_loss_pct=str(settings.max_daily_loss_pct), max_weekly_loss_pct=str(settings.max_weekly_loss_pct),
        max_spread=str(settings.max_spread), max_exposure_pct=str(settings.max_exposure_pct),
        max_simultaneous_trades=settings.max_simultaneous_trades, min_reward_risk=str(settings.minimum_reward_risk),
    )
    repository = TradeJournalRepository()
    with SessionLocal() as session:
        repository.record_heartbeat(session, "shadow-worker", "RUNNING", "Shadow cycle started")
        similar_performance = _similar_session_performance(session)
    try:
        observation_active = bool(settings.observation_mode_until and datetime.now(UTC) < settings.observation_mode_until)
        result = ShadowModeRunner().run_once(
            MetaTrader5Gateway.from_installed_package(allow_orders=False),
            profile,
            build_economic_calendar_provider(settings),
            settings.max_tick_age_seconds,
            settings.max_bar_age_seconds,
            settings.mt5_server_utc_offset_hours,
            Decimal(str(settings.observation_min_market_quality)) if observation_active else Decimal("7.00"),
            observation_active,
            similar_performance,
        )
    except Exception as exc:
        with SessionLocal() as session:
            repository.record_heartbeat(session, "shadow-worker", "ERROR", f"Shadow cycle failed: {type(exc).__name__}")
        raise
    else:
        with SessionLocal() as session:
            repository.record_preview(session, result)
            collective_events = _collective_events(session, result.correlation_id, result.final_message)
            session.rollback()
            repository.record_collective_events(session, result.correlation_id, collective_events)
            repository.record_heartbeat(session, "shadow-worker", "HEALTHY", "Last shadow cycle completed; execution disabled")
    print(result.model_dump_json())


if __name__ == "__main__": run_once()
