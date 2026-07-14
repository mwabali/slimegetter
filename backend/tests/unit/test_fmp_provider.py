from app.infrastructure.market_data.providers import FmpEconomicCalendarProvider


def test_fmp_provider_keeps_key_private() -> None:
    provider = FmpEconomicCalendarProvider("secret-value")
    assert "secret-value" not in repr(provider)
