from decimal import Decimal
from uuid import uuid4

import pytest

from app.agents.erwin.service import CommanderErwinService
from app.infrastructure.mt5.gateway import ExecutionDisabledError, MockMt5Gateway
from app.application.execution import DemoExecutionService
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
