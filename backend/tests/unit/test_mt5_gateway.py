from datetime import UTC, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.agents.erwin.service import CommanderErwinService
from app.infrastructure.mt5.gateway import ExecutionDisabledError, MockMt5Gateway
from app.infrastructure.mt5.gateway import MetaTrader5Gateway, Mt5Position
from app.application.execution import DemoExecutionService
from app.application.avenger import AvengerBracketBuilder
from app.domain.market.models import MarketSession, MarketSnapshot
from tests.unit.test_erwin import account, profile, proposal


def test_demo_execution_needs_explicit_enablement() -> None:
    trade = proposal(); decision = CommanderErwinService().evaluate(trade, account(), profile(), Decimal("0.5"))
    with pytest.raises(ExecutionDisabledError):
        DemoExecutionService(MockMt5Gateway(account(), enabled=True), False, "demo").submit(trade, decision)


def test_mock_order_is_idempotent() -> None:
    trade = proposal(); decision = CommanderErwinService().evaluate(trade, account(), profile(), Decimal("0.5"))
    service = DemoExecutionService(MockMt5Gateway(account(), enabled=True), True, "demo")
    assert service.submit(trade, decision) == service.submit(trade, decision)


def test_demo_execution_rejects_cross_cycle_approval() -> None:
    trade = proposal(); decision = CommanderErwinService().evaluate(trade, account(), profile(), Decimal("0.5"))
    mismatched = decision.model_copy(update={"correlation_id": uuid4()})
    with pytest.raises(PermissionError):
        DemoExecutionService(MockMt5Gateway(account(), enabled=True), True, "demo").submit(trade, mismatched)


def test_demo_execution_submits_approved_avenger_bracket(monkeypatch) -> None:
    from app.config.settings import get_settings

    monkeypatch.setenv("XAU_AVENGER_PROFILE_MODE", "FLASH")
    get_settings.cache_clear()
    try:
        market = MarketSnapshot(
            bid=Decimal("4010.00"),
            ask=Decimal("4010.20"),
            atr=Decimal("1.00"),
            ema_fast=Decimal("4011"),
            ema_slow=Decimal("4010"),
            rsi=Decimal("60"),
            trend_strength=Decimal("5"),
            volatility_score=Decimal("7"),
            liquidity_score=Decimal("8"),
            momentum_score=Decimal("8"),
            session=MarketSession.LONDON,
        )
        plan = AvengerBracketBuilder().build(market, get_settings(), Decimal("0.25"), uuid4())
        commander = CommanderErwinService()
        buy_decision = commander.evaluate(plan.buy.proposal, account(), profile(), Decimal("0.2"))
        sell_decision = commander.evaluate(plan.sell.proposal, account(), profile(), Decimal("0.2"))
        gateway = MockMt5Gateway(account(), enabled=True)
        tickets = DemoExecutionService(gateway, True, "demo").submit_bracket(plan, buy_decision, sell_decision)
        assert tickets == "demo-buy_stop-1,demo-sell_stop-2"
        assert [order.order_type for order in gateway.orders] == ["BUY_STOP", "SELL_STOP"]
    finally:
        get_settings.cache_clear()


def test_sltp_request_uses_mt5_supported_fields_only() -> None:
    class FakeMt5:
        TRADE_ACTION_SLTP = 6
        TRADE_RETCODE_DONE = 10009

        def __init__(self) -> None:
            self.request = None

        def symbol_info(self, symbol):
            return SimpleNamespace(digits=2)

        def symbol_select(self, symbol, enabled):
            return True

        def order_send(self, request):
            self.request = request
            return SimpleNamespace(retcode=self.TRADE_RETCODE_DONE)

        def last_error(self):
            return (0, "")

    fake = FakeMt5()
    gateway = MetaTrader5Gateway(fake, allow_orders=True, kill_switch=lambda: False)
    original = Mt5Position(
        ticket="42", symbol="XAUUSD", side="BUY", volume=Decimal("0.01"),
        price_open=Decimal("4010"), stop_loss=Decimal("4000"),
        take_profit=Decimal("4020"), profit=Decimal("1.2"),
        opened_at=datetime.now(UTC),
    )
    confirmed = original.__class__(
        ticket=original.ticket, symbol=original.symbol, side=original.side,
        volume=original.volume, price_open=original.price_open,
        stop_loss=Decimal("4005"), take_profit=original.take_profit,
        profit=original.profit, opened_at=original.opened_at,
    )
    gateway.get_positions = lambda symbol=None: (confirmed,)

    result = gateway.modify_position_protection(original, Decimal("4005"), Decimal("4020"), "ignored-comment")

    assert result.stop_loss == Decimal("4005")
    assert fake.request["action"] == fake.TRADE_ACTION_SLTP
    assert fake.request["position"] == 42
    assert "comment" not in fake.request
    assert "magic" not in fake.request


def test_pending_order_falls_back_when_expiration_request_is_rejected() -> None:
    class FakeMt5:
        TRADE_ACTION_PENDING = 5
        ORDER_TYPE_BUY_STOP = 4
        ORDER_TYPE_SELL_STOP = 5
        ORDER_FILLING_RETURN = 2
        ORDER_FILLING_IOC = 1
        ORDER_FILLING_FOK = 0
        ORDER_TIME_SPECIFIED = 2
        ORDER_TIME_GTC = 0
        TRADE_RETCODE_DONE = 10009
        TRADE_RETCODE_PLACED = 10008

        def __init__(self) -> None:
            self.requests = []

        def symbol_info(self, symbol):
            return SimpleNamespace(digits=2)

        def symbol_select(self, symbol, enabled):
            return True

        def terminal_info(self):
            return SimpleNamespace(trade_allowed=True, tradeapi_disabled=False)

        def account_info(self):
            return SimpleNamespace(trade_allowed=True, trade_expert=True)

        def order_send(self, request):
            self.requests.append(request)
            if "expiration" in request:
                return None
            return SimpleNamespace(retcode=self.TRADE_RETCODE_PLACED, order=99, deal=0, comment="")

        def last_error(self):
            return (1, "Success")

    fake = FakeMt5()
    gateway = MetaTrader5Gateway(fake, allow_orders=True, kill_switch=lambda: False)
    ticket = gateway.submit_pending_order(
        proposal(), "BUY_STOP", "xau-avenger:FLASH:BUY", datetime.now(UTC) + timedelta(minutes=30)
    )

    assert ticket == "99"
    assert len(fake.requests) == 2
    assert "expiration" in fake.requests[0]
    assert "expiration" not in fake.requests[1]
