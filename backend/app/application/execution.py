from app.application.avenger import AvengerBracketPlan
from app.domain.trading.models import ProposalStatus, RiskDecision, TradeProposal
from app.infrastructure.mt5.gateway import ExecutionDisabledError, Mt5Gateway


class DemoExecutionService:
    """Only an Erwin-approved proposal may cross this demo-only boundary."""
    def __init__(self, gateway: Mt5Gateway, execution_enabled: bool, trading_mode: str) -> None:
        self._gateway, self._execution_enabled, self._trading_mode = gateway, execution_enabled, trading_mode

    def submit(self, proposal: TradeProposal, decision: RiskDecision) -> str:
        if not self._execution_enabled or self._trading_mode != "demo":
            raise ExecutionDisabledError("Execution requires explicit demo-mode enablement")
        if decision.status is not ProposalStatus.APPROVED or decision.proposal_id != proposal.id or decision.correlation_id != proposal.correlation_id:
            raise PermissionError("Only Commander Erwin-approved proposals may be submitted")
        return self._gateway.submit_approved_trade(proposal, str(proposal.id))

    def submit_bracket(
        self,
        plan: AvengerBracketPlan,
        buy_decision: RiskDecision,
        sell_decision: RiskDecision,
    ) -> str:
        if not self._execution_enabled or self._trading_mode != "demo":
            raise ExecutionDisabledError("Execution requires explicit demo-mode enablement")
        for leg, decision in ((plan.buy, buy_decision), (plan.sell, sell_decision)):
            proposal = leg.proposal
            if (
                decision.status is not ProposalStatus.APPROVED
                or decision.proposal_id != proposal.id
                or decision.correlation_id != proposal.correlation_id
            ):
                raise PermissionError("Only Commander Erwin-approved bracket legs may be submitted")
        buy_ticket = self._gateway.submit_pending_order(
            plan.buy.proposal,
            plan.buy.order_type,
            plan.buy.comment,
            plan.expires_at,
        )
        try:
            sell_ticket = self._gateway.submit_pending_order(
                plan.sell.proposal,
                plan.sell.order_type,
                plan.sell.comment,
                plan.expires_at,
            )
        except Exception:
            get_orders = getattr(self._gateway, "get_orders", None)
            cancel_order = getattr(self._gateway, "cancel_order", None)
            if callable(get_orders) and callable(cancel_order):
                for order in get_orders(plan.symbol):
                    if order.ticket == buy_ticket:
                        cancel_order(order, "xau-avenger:partial-bracket")
                        break
            raise
        return f"{buy_ticket},{sell_ticket}"
