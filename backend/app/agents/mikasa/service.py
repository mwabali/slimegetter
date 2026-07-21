from decimal import Decimal

from app.agents.mikasa.models import MikasaAssessment, SimilarMarketPerformance, TradingPermission
from app.domain.market.models import MarketSession, MarketSnapshot


class MikasaService:
    """Continuously observes market quality and recalls similar outcomes.

    ``legacy_permission`` records the previous threshold-based decision so the
    dashboard and shadow tests can compare behavior. Mikasa never vetoes a
    proposal: every input is evidence for confidence, sizing and explanation.
    Erwin remains the only deterministic risk authority.
    """

    def assess(
        self,
        market: MarketSnapshot,
        max_spread: Decimal,
        minimum_quality: Decimal = Decimal("7.00"),
        observation_override: bool = False,
        minimum_liquidity: Decimal = Decimal("3.00"),
        similar_performance: SimilarMarketPerformance | None = None,
    ) -> MikasaAssessment:
        score = (
            market.trend_strength * Decimal("0.30")
            + market.volatility_score * Decimal("0.20")
            + market.liquidity_score * Decimal("0.30")
            + market.momentum_score * Decimal("0.20")
        ).quantize(Decimal("0.01"))
        reasons: list[str] = [f"Market quality score: {score}/10"]
        is_session_allowed = market.session in {MarketSession.LONDON, MarketSession.NEW_YORK}
        warnings: list[str] = []
        if market.spread > max_spread:
            warnings.append("Spread is above profile preference; reported to Erwin as risk evidence")
        if market.liquidity_score < minimum_liquidity:
            warnings.append(f"Liquidity is below reference level {minimum_liquidity}; no Mikasa veto applied")
        if not is_session_allowed:
            reasons.append(f"{market.session.value} is outside Erwin's configured trading sessions; Erwin will decide")
        reasons.extend(warnings)
        if observation_override:
            reasons.append(f"DEMO EXPLORATION FLOOR: {minimum_quality}; Mikasa remains advisory and Erwin/Avenger retain execution authority")
        legacy_permission = TradingPermission.ALLOW if is_session_allowed and market.spread <= max_spread and score >= minimum_quality else TradingPermission.WAIT
        if score < minimum_quality:
            reasons.append(f"Legacy threshold would WAIT below {minimum_quality}; advisory mode remains available")
        performance = similar_performance or SimilarMarketPerformance()
        quality_multiplier = Decimal("0.70") + score / Decimal("25")
        evidence_multiplier = Decimal("1.00")
        calibration_status = "COLLECTING_EVIDENCE"
        if performance.sample_size >= 5 and performance.win_rate is not None:
            evidence_multiplier = Decimal("0.80") + performance.win_rate * Decimal("0.40")
            calibration_status = "EVIDENCE_INFORMED"
            reasons.append(
                f"Similar-condition history: {performance.sample_size} trades, "
                f"{(performance.win_rate * Decimal('100')).quantize(Decimal('0.1'))}% wins, "
                f"net P/L {performance.net_pnl}"
            )
        else:
            reasons.append(f"Similar-condition history is still sparse ({performance.sample_size} trades)")
        confidence_multiplier = max(Decimal("0.50"), min(Decimal("1.25"), (quality_multiplier * evidence_multiplier).quantize(Decimal("0.01"))))
        risk_multiplier = max(Decimal("0.50"), min(Decimal("1.15"), confidence_multiplier))
        regime = "TRENDING" if market.trend_strength >= Decimal("7") else "RANGING"
        return MikasaAssessment(
            permission=TradingPermission.ALLOW,
            legacy_permission=legacy_permission,
            advisory_mode="CONTINUOUS_MARKET_INTELLIGENCE",
            quality_score=score,
            regime=regime,
            score_components={
                "trend": market.trend_strength,
                "volatility": market.volatility_score,
                "liquidity": market.liquidity_score,
                "momentum": market.momentum_score,
                "spread": market.spread,
            },
            calibration_status=calibration_status,
            similar_market_performance=performance,
            minimum_quality_required=minimum_quality,
            observation_override_active=observation_override,
            confidence_multiplier=confidence_multiplier,
            risk_multiplier=risk_multiplier,
            hard_blocked=False,
            reasons=tuple(reasons),
        )
