from decimal import Decimal

from app.domain.trading.models import AccountSnapshot, ProposalStatus, RiskDecision, RiskProfile, Side, TradeProposal
from app.application.defensive_risk import RiskState, RiskStateAssessment


class CommanderErwinService:
    """Calculated-risk commander with explicit account-survival limits.

    Imperfect opportunity conditions reduce committed size instead of causing
    automatic rejection. Rejection is reserved for invalid orders or exhausted
    account capacity. No AI and no broker side effects are used here.
    """

    def evaluate(
        self,
        proposal: TradeProposal,
        account: AccountSnapshot,
        profile: RiskProfile,
        current_spread: Decimal,
        execution_locked: bool = False,
        defensive_risk: RiskStateAssessment | None = None,
    ) -> RiskDecision:
        survival_rejections: list[str] = []
        accepted_warnings: list[str] = []
        size_multiplier = Decimal("1.00")
        if execution_locked:
            survival_rejections.append("Execution locked: unresolved critical broker incident requires human resolution")
        if defensive_risk is not None:
            if defensive_risk.state in {RiskState.HALTED, RiskState.UNKNOWN}:
                survival_rejections.append(
                    f"Defensive risk state {defensive_risk.state.value}: {defensive_risk.state_reason}"
                )
            elif defensive_risk.new_entries_blocked:
                survival_rejections.append(
                    f"Defensive risk cooldown active until {defensive_risk.cooldown_until}"
                )
            elif defensive_risk.risk_multiplier < Decimal("1"):
                accepted_warnings.append(
                    f"Defensive risk state {defensive_risk.state.value} will limit new volume to {defensive_risk.risk_multiplier}x before submission"
                )
        if proposal.session not in profile.allowed_sessions:
            accepted_warnings.append(f"Session {proposal.session} is outside the preferred campaign window")
            size_multiplier *= Decimal("0.60")
        if current_spread > profile.max_spread:
            accepted_warnings.append(f"Spread {current_spread} exceeds preference {profile.max_spread}; opportunity retained at reduced size")
            size_multiplier *= max(Decimal("0.25"), profile.max_spread / current_spread)
        if account.open_position_count >= profile.max_simultaneous_trades:
            survival_rejections.append("No campaign capacity: maximum simultaneous trades reached")
        remaining_exposure = profile.max_exposure_pct - account.current_exposure_pct
        if remaining_exposure <= 0:
            survival_rejections.append("No account exposure capacity remains")
        elif proposal.expected_risk_pct > remaining_exposure:
            accepted_warnings.append("Position reduced to remaining account exposure capacity")
            size_multiplier = min(size_multiplier, remaining_exposure / proposal.expected_risk_pct)
        if proposal.expected_risk_pct > profile.risk_per_trade_pct:
            accepted_warnings.append("Position reduced to the per-trade campaign budget")
            size_multiplier = min(size_multiplier, profile.risk_per_trade_pct / proposal.expected_risk_pct)
        daily_loss_limit = -(account.equity * profile.max_daily_loss_pct / Decimal("100"))
        if account.realized_daily_pnl <= daily_loss_limit:
            survival_rejections.append("Account-survival stop: maximum daily loss reached")
        weekly_loss_limit = -(account.equity * profile.max_weekly_loss_pct / Decimal("100"))
        if account.realized_weekly_pnl <= weekly_loss_limit:
            survival_rejections.append("Account-survival stop: maximum weekly loss reached")
        if account.free_margin <= Decimal("0"):
            survival_rejections.append("No free margin available")
        if not self._has_valid_levels(proposal):
            survival_rejections.append("Stop loss / take profit directions are invalid")
        if proposal.reward_risk_ratio() < profile.min_reward_risk:
            accepted_warnings.append("Reward-risk is below preference; commitment reduced rather than abandoned")
            size_multiplier *= Decimal("0.50")
        size_multiplier = max(Decimal("0.10"), min(Decimal("1.00"), size_multiplier.quantize(Decimal("0.01"))))
        if survival_rejections:
            reasons = tuple((*survival_rejections, *accepted_warnings))
            posture = "SURVIVAL_STOP"
        elif accepted_warnings:
            reasons = (f"Calculated risk accepted at {size_multiplier * 100}% size", *accepted_warnings)
            posture = "CALCULATED_OFFENSIVE"
        else:
            reasons = ("Full-size opportunity accepted; all campaign constraints are healthy",)
            posture = "FULL_COMMITMENT"
        return RiskDecision(
            proposal_id=proposal.id,
            correlation_id=proposal.correlation_id,
            status=ProposalStatus.REJECTED if survival_rejections else ProposalStatus.APPROVED,
            reasons=reasons,
            risk_posture=posture,
            recommended_size_multiplier=size_multiplier,
            accepted_warnings=tuple(accepted_warnings),
        )

    @staticmethod
    def _has_valid_levels(proposal: TradeProposal) -> bool:
        if proposal.side is Side.BUY:
            return proposal.stop_loss < proposal.entry_price < proposal.take_profit
        return proposal.take_profit < proposal.entry_price < proposal.stop_loss
