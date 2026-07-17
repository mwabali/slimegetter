from functools import lru_cache
from datetime import datetime
from typing import Literal

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime configuration. Execution is deliberately disabled by default."""

    model_config = SettingsConfigDict(env_file=".env", env_prefix="XAU_", extra="ignore")

    environment: Literal["development", "test", "production"] = "development"
    database_url: str = "sqlite:///./xauusd.db"
    execution_enabled: bool = False
    trading_mode: Literal["demo", "live"] = "demo"
    demo_trading_confirmed: bool = False
    demo_entry_enabled: bool = True
    kill_switch_active: bool = True
    max_tick_age_seconds: int = Field(default=15, ge=1, le=300)
    max_bar_age_seconds: int = Field(default=600, ge=60, le=3600)
    mt5_server_utc_offset_hours: int = Field(default=0, ge=-14, le=14)
    manual_calendar_path: str = "data/verified_events.json"
    observation_mode_until: datetime | None = None
    observation_min_market_quality: float = Field(default=4.0, ge=0, le=10)
    demo_exploration_enabled: bool = False
    demo_exploration_min_market_quality: float = Field(default=0.0, ge=0, le=10)
    demo_position_manager_enabled: bool = False
    demo_position_poll_seconds: int = Field(default=5, ge=1, le=300)
    demo_position_max_minutes: int = Field(default=45, ge=1, le=1440)
    demo_position_profit_target_usd: float = Field(default=0.50, ge=0)
    demo_position_stop_loss_usd: float = Field(default=6.00, ge=0)
    demo_position_close_on_opposite_signal: bool = True
    demo_position_trailing_activation_usd: float = Field(default=0.50, ge=0)
    demo_position_trailing_giveback_usd: float = Field(default=0.30, ge=0)
    demo_position_trailing_giveback_pct: float = Field(default=0.35, ge=0, le=1)
    demo_position_state_path: str = "../work/position-manager-state.json"
    api_title: str = "XAUUSD Mission Control API"
    max_risk_per_trade_pct: float = Field(default=0.25, gt=0, le=5)
    max_daily_loss_pct: float = Field(default=2.0, gt=0, le=20)
    max_weekly_loss_pct: float = Field(default=5.0, gt=0, le=40)
    max_spread: float = Field(default=1.0, gt=0)
    max_exposure_pct: float = Field(default=1.0, gt=0, le=100)
    max_simultaneous_trades: int = Field(default=1, gt=0, le=100)
    minimum_reward_risk: float = Field(default=1.5, gt=0)
    openai_model: str = "gpt-4.1-mini"
    openai_api_key: str | None = Field(default=None, validation_alias="OPENAI_API_KEY")
    levi_enabled: bool = True
    levi_min_interval_minutes: int = Field(default=30, ge=5, le=1440)
    auth_enabled: bool = False
    admin_api_key: str | None = None
    operator_api_key: str | None = None
    fmp_api_key: str | None = Field(default=None, validation_alias="FMP_API_KEY")
    finnhub_api_key: str | None = Field(default=None, validation_alias="FINNHUB_API_KEY")
    news_provider: str = "official_us"

    @model_validator(mode="after")
    def require_production_auth(self) -> "Settings":
        if self.environment == "production" and (not self.auth_enabled or not self.admin_api_key or not self.operator_api_key):
            raise ValueError("Production requires XAU_AUTH_ENABLED=true and both admin/operator API keys")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
