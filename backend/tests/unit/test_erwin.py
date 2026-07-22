from decimal import Decimal

from app.agents.erwin.service import CommanderErwinService
from app.domain.trading.models import AccountSnapshot, ProposalStatus, RiskProfile, Side, TradeProposal


def proposal(**changes: object) -> TradeProposal:
    values: dict[str, object] = {
        "side": Side.BUY,
        "volume": "0.01",
        "entry_price": "2300",
        "stop_loss": "2295",
        "take_profit": "2312",
        "confidence": "0.75",
        "reasons": ("Trend confirmed",),
        "indicators_used": ("EMA",),
        "expected_risk_pct": "0.20",
        "session": "LONDON",
    }
    values.update(changes)
    return TradeProposal(**values)


def account(**changes: object) -> AccountSnapshot:
    values: dict[str, object] = {
        "account_id": "demo-1", "equity": "10000", "free_margin": "9000",
        "open_position_count": 0, "current_exposure_pct": "0", "realized_daily_pnl": "0",
        "realized_weekly_pnl": "0",
    }
    values.update(changes)
    return AccountSnapshot(**values)


def profile() -> RiskProfile:
    return RiskProfile(risk_per_trade_pct="0.25", max_daily_loss_pct="2", max_weekly_loss_pct="5", max_spread="1.5", max_exposure_pct="1", max_simultaneous_trades=1, min_reward_risk="1.5")


def test_approves_valid_proposal() -> None:
    result = CommanderErwinService().evaluate(proposal(), account(), profile(), Decimal("0.5"))
    assert result.status is ProposalStatus.APPROVED


def test_rejects_excessive_spread_and_invalid_stop() -> None:
    result = CommanderErwinService().evaluate(proposal(stop_loss="2301"), account(), profile(), Decimal("2"))
    assert result.status is ProposalStatus.REJECTED
    assert any("Spread" in reason for reason in result.reasons)
    assert any("Stop loss" in reason for reason in result.reasons)


def test_rejects_after_daily_loss_limit() -> None:
    result = CommanderErwinService().evaluate(proposal(), account(realized_daily_pnl="-200"), profile(), Decimal("0.5"))
    assert result.status is ProposalStatus.REJECTED
    assert any("maximum daily loss" in reason for reason in result.reasons)


def test_accepts_wide_spread_as_calculated_risk_at_reduced_size() -> None:
    result = CommanderErwinService().evaluate(proposal(), account(), profile(), Decimal("3"))
    assert result.status is ProposalStatus.APPROVED
    assert result.risk_posture == "CALCULATED_OFFENSIVE"
    assert result.recommended_size_multiplier < Decimal("1")
    assert any("Spread" in warning for warning in result.accepted_warnings)


def test_scales_excess_risk_instead_of_abandoning_valid_opportunity() -> None:
    result = CommanderErwinService().evaluate(proposal(expected_risk_pct="0.50"), account(), profile(), Decimal("0.5"))
    assert result.status is ProposalStatus.APPROVED
    assert result.recommended_size_multiplier == Decimal("0.50")


def test_rejects_when_execution_is_locked() -> None:
    result = CommanderErwinService().evaluate(proposal(), account(), profile(), Decimal("0.5"), execution_locked=True)
    assert result.status is ProposalStatus.REJECTED
    assert any("Execution locked" in reason for reason in result.reasons)


def test_demo_weekly_loss_override_bypasses_only_weekly_stop() -> None:
    result = CommanderErwinService().evaluate(
        proposal(),
        account(realized_weekly_pnl="-600"),
        profile(),
        Decimal("0.5"),
        override_weekly_loss_stop=True,
    )
    assert result.status is ProposalStatus.APPROVED
    assert any("DEMO OVERRIDE" in warning for warning in result.accepted_warnings)
