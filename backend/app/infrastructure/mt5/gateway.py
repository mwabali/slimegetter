from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from decimal import Decimal
import os
import tempfile
import time
from threading import RLock
from typing import Any, Callable, Protocol

from app.domain.trading.models import AccountSnapshot, Side, TradeProposal


class Mt5Gateway(Protocol):
    """Port for the Windows-hosted MT5 terminal adapter."""
    def get_account_snapshot(self) -> AccountSnapshot: ...
    def get_symbol_specification(self, symbol: str) -> object: ...
    def get_tick(self, symbol: str) -> "Mt5Tick": ...
    def submit_approved_trade(self, proposal: TradeProposal, idempotency_key: str) -> str: ...


class ExecutionDisabledError(RuntimeError): pass
class Mt5AdapterError(RuntimeError): pass


@dataclass(frozen=True)
class Mt5Tick:
    symbol: str
    bid: Decimal
    ask: Decimal
    time_msc: int


@dataclass(frozen=True)
class Mt5Bar:
    time: datetime
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal


@dataclass(frozen=True)
class Mt5Position:
    ticket: str
    symbol: str
    side: str
    volume: Decimal
    price_open: Decimal
    stop_loss: Decimal | None
    take_profit: Decimal | None
    profit: Decimal
    opened_at: datetime | None


@dataclass(frozen=True)
class Mt5Fill:
    deal_ticket: str
    order_ticket: str | None
    symbol: str
    side: str
    volume: Decimal
    price: Decimal
    profit: Decimal
    filled_at: datetime
    entry: str = "IN"


class DisabledMt5Gateway:
    """Safe default: production startup cannot reach an MT5 terminal."""
    def _disabled(self) -> None: raise ExecutionDisabledError("MT5 execution is disabled")
    def get_account_snapshot(self) -> AccountSnapshot: self._disabled(); raise AssertionError
    def get_symbol_specification(self, symbol: str) -> object: self._disabled(); raise AssertionError
    def get_tick(self, symbol: str) -> Mt5Tick: self._disabled(); raise AssertionError
    def submit_approved_trade(self, proposal: TradeProposal, idempotency_key: str) -> str: self._disabled(); raise AssertionError


class MetaTrader5Gateway:
    """Concrete demo adapter. Importing it never connects; callers must explicitly connect."""
    _terminal_lock = RLock()

    def __init__(self, mt5: Any, allow_orders: bool = False, kill_switch: Callable[[], bool] | None = None) -> None:
        self._mt5, self._allow_orders, self._kill_switch = mt5, allow_orders, kill_switch or (lambda: False)
        self._orders: dict[str, str] = {}
        self._lock_held = False
        self._process_lock_file: Any | None = None

    def _acquire_process_lock(self) -> None:
        """Serialize terminal initialize/shutdown across Python processes on Windows."""
        import msvcrt
        path = os.path.join(tempfile.gettempdir(), "xauusd-mt5-terminal.lock")
        handle = open(path, "a+b")  # noqa: SIM115 - handle is held for the gateway lifetime
        if handle.tell() == 0:
            handle.write(b"0"); handle.flush()
        deadline = time.monotonic() + 30
        while True:
            try:
                handle.seek(0); msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                self._process_lock_file = handle
                return
            except OSError:
                if time.monotonic() >= deadline:
                    handle.close()
                    raise Mt5AdapterError("Timed out waiting for exclusive MT5 terminal access")
                time.sleep(0.1)

    def _release_process_lock(self) -> None:
        if self._process_lock_file is None: return
        import msvcrt
        try:
            self._process_lock_file.seek(0)
            msvcrt.locking(self._process_lock_file.fileno(), msvcrt.LK_UNLCK, 1)
        finally:
            self._process_lock_file.close(); self._process_lock_file = None

    @classmethod
    def from_installed_package(
        cls,
        allow_orders: bool = False,
        kill_switch: Callable[[], bool] | None = None,
    ) -> "MetaTrader5Gateway":
        try:
            import MetaTrader5 as mt5
        except ImportError as exc:
            raise Mt5AdapterError("Install backend[mt5] on the Windows MT5 worker") from exc
        return cls(mt5, allow_orders, kill_switch)

    def connect(self) -> None:
        self._terminal_lock.acquire()
        self._lock_held = True
        try:
            self._acquire_process_lock()
            # A terminal can briefly report authorization failure immediately after
            # another process calls shutdown.  Keep the critical section locked and
            # allow that local IPC session a short, bounded recovery window.
            initialized = False
            last_error: object = None
            for attempt in range(4):
                initialized = bool(self._mt5.initialize())
                if initialized:
                    break
                last_error = self._mt5.last_error()
                if attempt < 3:
                    time.sleep(0.5 * (attempt + 1))
            if not initialized:
                raise Mt5AdapterError(f"MT5 initialize failed: {last_error}")
            info = self._mt5.account_info()
            if info is None: raise Mt5AdapterError("MT5 account information is unavailable")
            if getattr(info, "trade_mode", None) != getattr(self._mt5, "ACCOUNT_TRADE_MODE_DEMO", object()):
                raise Mt5AdapterError("Refusing non-demo MT5 account")
        except Exception:
            self._release_process_lock()
            self._lock_held = False
            self._terminal_lock.release()
            raise

    def shutdown(self) -> None:
        try:
            self._mt5.shutdown()
        finally:
            self._release_process_lock()
            if self._lock_held:
                self._lock_held = False
                self._terminal_lock.release()

    def get_account_snapshot(self) -> AccountSnapshot:
        info = self._mt5.account_info()
        if info is None: raise Mt5AdapterError("MT5 account information is unavailable")
        now = datetime.now(UTC)
        day_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        week_start = day_start - timedelta(days=day_start.weekday())
        deals = self._mt5.history_deals_get(week_start, now)
        if deals is None:
            raise Mt5AdapterError(f"MT5 deal history unavailable: {self._mt5.last_error()}")
        trade_types = {getattr(self._mt5, "DEAL_TYPE_BUY", 0), getattr(self._mt5, "DEAL_TYPE_SELL", 1)}
        trade_deals = tuple(row for row in deals if getattr(row, "type", None) in trade_types and str(getattr(row, "symbol", "")).upper() == "XAUUSD")
        def net(row: Any) -> Decimal:
            return sum((Decimal(str(getattr(row, name, 0) or 0)) for name in ("profit", "commission", "swap", "fee")), Decimal("0"))
        weekly_pnl = sum((net(row) for row in trade_deals), Decimal("0"))
        daily_pnl = sum((net(row) for row in trade_deals if datetime.fromtimestamp(int(row.time), UTC) >= day_start), Decimal("0"))
        positions = self._mt5.positions_get()
        if positions is None:
            raise Mt5AdapterError(f"MT5 positions unavailable: {self._mt5.last_error()}")
        return AccountSnapshot(account_id=str(info.login), balance=Decimal(str(info.balance)), equity=Decimal(str(info.equity)), free_margin=Decimal(str(info.margin_free)), used_margin=Decimal(str(info.margin)), margin_level=Decimal(str(info.margin_level)), floating_pnl=Decimal(str(info.profit)), currency=str(info.currency), leverage=int(info.leverage), open_position_count=len(positions), current_exposure_pct=Decimal("0"), realized_daily_pnl=daily_pnl, realized_weekly_pnl=weekly_pnl)

    def get_symbol_specification(self, symbol: str) -> object:
        info = self._mt5.symbol_info(symbol)
        if info is None: raise Mt5AdapterError(f"Symbol unavailable: {symbol}")
        return info

    def get_tick(self, symbol: str) -> Mt5Tick:
        if not self._mt5.symbol_select(symbol, True):
            raise Mt5AdapterError(f"Unable to select symbol: {symbol}")
        tick = self._mt5.symbol_info_tick(symbol)
        if tick is None: raise Mt5AdapterError(f"Tick unavailable: {symbol}")
        return Mt5Tick(symbol=symbol, bid=Decimal(str(tick.bid)), ask=Decimal(str(tick.ask)), time_msc=int(tick.time_msc))

    def get_recent_bars(self, symbol: str, count: int = 100) -> tuple[Mt5Bar, ...]:
        if not self._mt5.symbol_select(symbol, True):
            raise Mt5AdapterError(f"Unable to select symbol: {symbol}")
        rates = self._mt5.copy_rates_from_pos(symbol, self._mt5.TIMEFRAME_M5, 0, count)
        if rates is None or len(rates) < 30: raise Mt5AdapterError("Insufficient M5 price history")
        return tuple(Mt5Bar(datetime.fromtimestamp(int(rate["time"]), UTC), Decimal(str(rate["open"])), Decimal(str(rate["high"])), Decimal(str(rate["low"])), Decimal(str(rate["close"]))) for rate in rates)

    def get_positions(self, symbol: str | None = None) -> tuple[Mt5Position, ...]:
        rows = self._mt5.positions_get(symbol=symbol) if symbol else self._mt5.positions_get()
        if rows is None:
            raise Mt5AdapterError(f"MT5 positions unavailable: {self._mt5.last_error()}")
        buy = getattr(self._mt5, "POSITION_TYPE_BUY", 0)
        return tuple(
            Mt5Position(
                ticket=str(row.ticket), symbol=str(row.symbol), side="BUY" if row.type == buy else "SELL",
                volume=Decimal(str(row.volume)), price_open=Decimal(str(row.price_open)),
                stop_loss=Decimal(str(row.sl)) if getattr(row, "sl", 0) else None,
                take_profit=Decimal(str(row.tp)) if getattr(row, "tp", 0) else None,
                profit=Decimal(str(row.profit)),
                opened_at=datetime.fromtimestamp(int(row.time), UTC) if getattr(row, "time", 0) else None,
            )
            for row in rows
        )

    def get_recent_fills(self, since: datetime, until: datetime | None = None) -> tuple[Mt5Fill, ...]:
        end = until or datetime.now(UTC)
        rows = self._mt5.history_deals_get(since, end)
        if rows is None:
            raise Mt5AdapterError(f"MT5 deal history unavailable: {self._mt5.last_error()}")
        buy = getattr(self._mt5, "DEAL_TYPE_BUY", 0)
        entry_names = {
            getattr(self._mt5, "DEAL_ENTRY_IN", 0): "IN",
            getattr(self._mt5, "DEAL_ENTRY_OUT", 1): "OUT",
            getattr(self._mt5, "DEAL_ENTRY_INOUT", 2): "INOUT",
            getattr(self._mt5, "DEAL_ENTRY_OUT_BY", 3): "OUT_BY",
        }
        return tuple(
            Mt5Fill(
                deal_ticket=str(row.ticket), order_ticket=str(row.order) if getattr(row, "order", 0) else None,
                symbol=str(row.symbol), side="BUY" if row.type == buy else "SELL",
                volume=Decimal(str(row.volume)), price=Decimal(str(row.price)),
                profit=Decimal(str(row.profit)), filled_at=datetime.fromtimestamp(int(row.time), UTC),
                entry=entry_names.get(getattr(row, "entry", 0), "IN"),
            )
            for row in rows if getattr(row, "symbol", "")
        )

    def submit_approved_trade(self, proposal: TradeProposal, idempotency_key: str) -> str:
        if not self._allow_orders or self._kill_switch(): raise ExecutionDisabledError("MT5 kill switch or order gate is active")
        if idempotency_key in self._orders: return self._orders[idempotency_key]
        if not self._mt5.symbol_select(proposal.symbol, True): raise Mt5AdapterError(f"Unable to select {proposal.symbol}")
        order_type = self._mt5.ORDER_TYPE_BUY if proposal.side is Side.BUY else self._mt5.ORDER_TYPE_SELL
        request = {"action": self._mt5.TRADE_ACTION_DEAL, "symbol": proposal.symbol, "volume": float(proposal.volume), "type": order_type, "sl": float(proposal.stop_loss), "tp": float(proposal.take_profit), "deviation": 20, "magic": 260713, "comment": f"xau:{idempotency_key[:20]}", "type_time": self._mt5.ORDER_TIME_GTC, "type_filling": self._mt5.ORDER_FILLING_IOC}
        result = self._mt5.order_send(request)
        if result is None or result.retcode != self._mt5.TRADE_RETCODE_DONE: raise Mt5AdapterError(f"MT5 order rejected: {getattr(result, 'comment', 'no result')}")
        ticket = str(result.order or result.deal)
        self._orders[idempotency_key] = ticket
        return ticket


@dataclass
class MockMt5Gateway:
    account: AccountSnapshot
    symbol_specification: object = object()
    enabled: bool = False
    positions: tuple[Mt5Position, ...] = ()
    fills: tuple[Mt5Fill, ...] = ()
    _orders: dict[str, str] = field(default_factory=dict)
    def get_account_snapshot(self) -> AccountSnapshot: return self.account
    def get_symbol_specification(self, symbol: str) -> object: return self.symbol_specification
    def get_tick(self, symbol: str) -> Mt5Tick: return Mt5Tick(symbol, Decimal("2300"), Decimal("2300.5"), 0)
    def get_positions(self, symbol: str | None = None) -> tuple[Mt5Position, ...]:
        return tuple(position for position in self.positions if symbol is None or position.symbol == symbol)
    def get_recent_fills(self, since: datetime, until: datetime | None = None) -> tuple[Mt5Fill, ...]:
        return tuple(fill for fill in self.fills if fill.filled_at >= since and (until is None or fill.filled_at <= until))
    def submit_approved_trade(self, proposal: TradeProposal, idempotency_key: str) -> str:
        if not self.enabled: raise ExecutionDisabledError("Mock execution is disabled")
        return self._orders.setdefault(idempotency_key, f"demo-order-{len(self._orders) + 1}")
