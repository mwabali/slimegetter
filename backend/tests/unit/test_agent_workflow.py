from datetime import UTC, datetime, timedelta
from decimal import Decimal

from app.agents.annie.models import NewsRiskStatus
from app.application.workflows.decision_preview import DecisionPreviewWorkflow
from app.domain.market.models import EconomicEvent, EventImpact, MarketSession, MarketSnapshot
from app.domain.trading.models import AccountSnapshot, ProposalStatus, RiskProfile


def market() -> MarketSnapshot:
    return MarketSnapshot(
        bid="2300", ask="2300.5", atr="4", ema_fast="2305", ema_slow="2295", rsi="60",
        trend_strength="8", volatility_score="8", liquidity_score="9", momentum_score="8",
        session=MarketSession.LONDON,
    )


def account() -> AccountSnapshot:
    return AccountSnapshot(
        account_id="demo", equity="10000", free_margin="9000", open_position_count=0,
        current_exposure_pct="0", realized_daily_pnl="0", realized_weekly_pnl="0",
    )


def profile() -> RiskProfile:
    return RiskProfile(
        risk_per_trade_pct="0.25", max_daily_loss_pct="2", max_weekly_loss_pct="5",
        max_spread="1", max_exposure_pct="1", max_simultaneous_trades=1, min_reward_risk="1.5",
    )


def test_safe_chain_produces_erwin_approved_proposal() -> None:
    result = DecisionPreviewWorkflow().run(market(), (), 0, account(), profile())
    assert result.annie.status is NewsRiskStatus.SAFE
    assert result.eren is not None
    assert result.erwin is not None
    assert result.erwin.status is ProposalStatus.APPROVED


def test_high_impact_event_stops_chain_before_eren() -> None:
    event = EconomicEvent(
        title="US CPI", impact=EventImpact.HIGH, scheduled_at=datetime.now(UTC) + timedelta(minutes=15),
        source="Economic calendar",
    )
    result = DecisionPreviewWorkflow().run(market(), (event,), 0, account(), profile())
    assert result.annie.status is NewsRiskStatus.NEWS_EVENT
    assert result.eren is None
    assert result.erwin is None
