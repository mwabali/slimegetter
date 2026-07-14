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
