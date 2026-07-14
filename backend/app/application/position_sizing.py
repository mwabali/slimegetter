from decimal import Decimal, ROUND_DOWN

from app.domain.trading.models import PositionSizeResult, Side, SymbolSpecification, TradeProposal


class PositionSizer:
    """Deterministically sizes XAUUSD volume; no broker or agent authority."""

    def size(self, proposal: TradeProposal, equity: Decimal, specification: SymbolSpecification) -> PositionSizeResult:
        risk_amount = equity * proposal.expected_risk_pct / Decimal("100")
        stop_distance = abs(proposal.entry_price - proposal.stop_loss)
        raw_volume = risk_amount / (stop_distance * specification.trade_contract_size)
        steps = (raw_volume / specification.volume_step).to_integral_value(rounding=ROUND_DOWN)
        volume = steps * specification.volume_step
        if volume < specification.volume_min:
            raise ValueError("Risk budget cannot support broker minimum volume")
        if volume > specification.volume_max:
            volume = specification.volume_max
        return PositionSizeResult(volume=volume, risk_amount=risk_amount, stop_distance=stop_distance)
