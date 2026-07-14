from app.config.settings import Settings
from app.infrastructure.market_data.providers import EconomicCalendarProvider, FinnhubEconomicCalendarProvider, FmpEconomicCalendarProvider, OfficialUsCalendarProvider, VerifiedManualCalendarProvider


def build_economic_calendar_provider(settings: Settings) -> EconomicCalendarProvider:
    if settings.news_provider == "manual":
        return VerifiedManualCalendarProvider(settings.manual_calendar_path)
    if settings.news_provider == "finnhub" and settings.finnhub_api_key:
        return FinnhubEconomicCalendarProvider(settings.finnhub_api_key)
    if settings.news_provider == "fmp" and settings.fmp_api_key:
        return FmpEconomicCalendarProvider(settings.fmp_api_key)
    return OfficialUsCalendarProvider()
