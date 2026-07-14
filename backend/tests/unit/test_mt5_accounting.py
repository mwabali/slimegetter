from datetime import UTC, datetime
from types import SimpleNamespace

from app.infrastructure.mt5.gateway import MetaTrader5Gateway


class FakeMt5:
    DEAL_TYPE_BUY = 0
    DEAL_TYPE_SELL = 1

    def account_info(self):
        return SimpleNamespace(login=1, balance=100, equity=102, margin_free=102, margin=0, margin_level=0, profit=2, currency="USD", leverage=100)

    def history_deals_get(self, _start, _end):
        now = int(datetime.now(UTC).timestamp())
        return (
            SimpleNamespace(type=2, symbol="", profit=5000, commission=0, swap=0, fee=0, time=now),
            SimpleNamespace(type=0, symbol="XAUUSD", profit=3, commission=-1, swap=0, fee=0, time=now),
            SimpleNamespace(type=0, symbol="EURUSD", profit=99, commission=0, swap=0, fee=0, time=now),
        )

    def positions_get(self):
        return ()


def test_account_pnl_excludes_deposits_and_non_gold_deals() -> None:
    snapshot = MetaTrader5Gateway(FakeMt5()).get_account_snapshot()
    assert snapshot.realized_daily_pnl == 2
    assert snapshot.realized_weekly_pnl == 2
