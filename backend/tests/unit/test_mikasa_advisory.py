from decimal import Decimal

from app.agents.mikasa.models import SimilarMarketPerformance, TradingPermission
from app.agents.mikasa.service import MikasaService
from app.application.workflows.decision_preview import DecisionPreviewWorkflow
from app.domain.market.models import MarketSession, MarketSnapshot
from app.domain.trading.models import AccountSnapshot, RiskProfile


def _market(score: str = "4.50", spread: str = "0.50") -> MarketSnapshot:
    return MarketSnapshot(
        bid="2300", ask=str(Decimal("2300") + Decimal(spread)), atr="4", ema_fast="2305", ema_slow="2295", rsi="60",
        session=MarketSession.LONDON, trend_strength=score, volatility_score=score,
        liquidity_score="8", momentum_score=score,
    )


def _account() -> AccountSnapshot:
    return AccountSnapshot(account_id="demo", equity="10000", free_margin="9000", open_position_count=0, current_exposure_pct="0", realized_daily_pnl="0", realized_weekly_pnl="0")


def _profile() -> RiskProfile:
    return RiskProfile(risk_per_trade_pct="0.25", max_daily_loss_pct="2", max_weekly_loss_pct="5", max_spread="1", max_exposure_pct="1", max_simultaneous_trades=1, min_reward_risk="1.5")


def test_low_score_is_advisory_not_a_blanket_wait() -> None:
    result = MikasaService().assess(_market(), Decimal("1"))
    assert result.permission is TradingPermission.ALLOW
    assert result.legacy_permission is TradingPermission.WAIT
    assert result.hard_blocked is False
    assert result.risk_multiplier < Decimal("1")


def test_spread_is_reported_but_never_blocked_by_mikasa() -> None:
    result = MikasaService().assess(_market(spread="2"), Decimal("1"))
    assert result.permission is TradingPermission.ALLOW
    assert result.hard_blocked is False
    assert any("no Mikasa veto" in reason or "reported to Erwin" in reason for reason in result.reasons)


def test_similar_market_results_inform_mikasa_without_becoming_a_veto() -> None:
    strong = SimilarMarketPerformance(sample_size=20, win_rate="0.70", average_reward_risk="1.8", net_pnl="240")
    weak = SimilarMarketPerformance(sample_size=20, win_rate="0.30", average_reward_risk="0.7", net_pnl="-120")
    strong_result = MikasaService().assess(_market(), Decimal("1"), similar_performance=strong)
    weak_result = MikasaService().assess(_market(), Decimal("1"), similar_performance=weak)
    assert strong_result.confidence_multiplier > weak_result.confidence_multiplier
    assert strong_result.permission is weak_result.permission is TradingPermission.ALLOW


def test_advisory_score_scales_eren_confidence_and_risk_before_erwin() -> None:
    result = DecisionPreviewWorkflow().run(_market(), (), 0, _account(), _profile())
    assert result.eren is not None
    assert result.eren.confidence < Decimal("0.65")
    assert result.eren.expected_risk_pct < Decimal("0.25")


def test_workflow_never_stops_at_mikasa_even_when_spread_is_wide() -> None:
    result = DecisionPreviewWorkflow().run(_market(spread="2"), (), 0, _account(), _profile())
    assert result.mikasa.permission is TradingPermission.ALLOW
    assert result.eren is not None
    assert result.erwin is not None
    assert result.erwin.status.value == "APPROVED"
    assert result.erwin.recommended_size_multiplier < Decimal("1")
    assert any("Spread" in warning for warning in result.erwin.accepted_warnings)
