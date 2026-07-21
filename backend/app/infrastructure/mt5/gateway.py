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
    def submit_pending_order(self, proposal: TradeProposal, order_type: str, comment: str, expires_at: datetime) -> str: ...
    def close_position(self, position: "Mt5Position", comment: str) -> str: ...
    def modify_position_protection(self, position: "Mt5Position", stop_loss: Decimal | None, take_profit: Decimal | None, comment: str) -> "Mt5Position": ...


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
class Mt5Order:
    ticket: str
    symbol: str
    side: str
    order_type: str
    volume: Decimal
    price_open: Decimal
    stop_loss: Decimal | None
    take_profit: Decimal | None
    magic: int | None = None
    comment: str | None = None


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
        resolved = self._resolve_symbol(symbol)
        tick = self._mt5.symbol_info_tick(resolved)
        if tick is None: raise Mt5AdapterError(f"Tick unavailable: {resolved}")
        return Mt5Tick(symbol=resolved, bid=Decimal(str(tick.bid)), ask=Decimal(str(tick.ask)), time_msc=int(tick.time_msc))

    def _resolve_symbol(self, symbol: str) -> str:
        for candidate in self._symbol_candidates(symbol):
            info = self._mt5.symbol_info(candidate)
            if info is not None and self._mt5.symbol_select(candidate, True):
                return candidate
        raise Mt5AdapterError(f"Unable to select symbol: {symbol}")

    @staticmethod
    def _symbol_candidates(symbol: str) -> tuple[str, ...]:
        raw = str(symbol or "XAUUSD")
        if raw.upper() == "XAUUSD":
            return (raw, "XAUUSD.vcn", "XAUUSD.vx", "XAUUSDm")
        return (raw,)

    def terminal_permissions(self) -> dict[str, bool | None]:
        terminal = self._mt5.terminal_info()
        account = self._mt5.account_info()
        return {
            "terminal_trade_allowed": getattr(terminal, "trade_allowed", None) if terminal else None,
            "terminal_tradeapi_disabled": getattr(terminal, "tradeapi_disabled", None) if terminal else None,
            "account_trade_allowed": getattr(account, "trade_allowed", None) if account else None,
            "account_trade_expert": getattr(account, "trade_expert", None) if account else None,
        }

    def get_recent_bars(self, symbol: str, count: int = 100) -> tuple[Mt5Bar, ...]:
        if not self._mt5.symbol_select(symbol, True):
            raise Mt5AdapterError(f"Unable to select symbol: {symbol}")
        rates = self._mt5.copy_rates_from_pos(symbol, self._mt5.TIMEFRAME_M5, 0, count)
        if rates is None or len(rates) < 30: raise Mt5AdapterError("Insufficient M5 price history")
        return tuple(Mt5Bar(datetime.fromtimestamp(int(rate["time"]), UTC), Decimal(str(rate["open"])), Decimal(str(rate["high"])), Decimal(str(rate["low"])), Decimal(str(rate["close"]))) for rate in rates)

    def get_positions(self, symbol: str | None = None) -> tuple[Mt5Position, ...]:
        resolved_symbol = self._resolve_symbol(symbol) if symbol else None
        rows = self._mt5.positions_get(symbol=resolved_symbol) if resolved_symbol else self._mt5.positions_get()
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

    def get_orders(self, symbol: str | None = None) -> tuple[Mt5Order, ...]:
        resolved_symbol = self._resolve_symbol(symbol) if symbol else None
        rows = self._mt5.orders_get(symbol=resolved_symbol) if resolved_symbol else self._mt5.orders_get()
        if rows is None:
            raise Mt5AdapterError(f"MT5 orders unavailable: {self._mt5.last_error()}")
        buy_types = {
            getattr(self._mt5, "ORDER_TYPE_BUY", 0),
            getattr(self._mt5, "ORDER_TYPE_BUY_LIMIT", 2),
            getattr(self._mt5, "ORDER_TYPE_BUY_STOP", 4),
            getattr(self._mt5, "ORDER_TYPE_BUY_STOP_LIMIT", 6),
        }
        names = {
            getattr(self._mt5, "ORDER_TYPE_BUY", 0): "BUY",
            getattr(self._mt5, "ORDER_TYPE_SELL", 1): "SELL",
            getattr(self._mt5, "ORDER_TYPE_BUY_LIMIT", 2): "BUY_LIMIT",
            getattr(self._mt5, "ORDER_TYPE_SELL_LIMIT", 3): "SELL_LIMIT",
            getattr(self._mt5, "ORDER_TYPE_BUY_STOP", 4): "BUY_STOP",
            getattr(self._mt5, "ORDER_TYPE_SELL_STOP", 5): "SELL_STOP",
            getattr(self._mt5, "ORDER_TYPE_BUY_STOP_LIMIT", 6): "BUY_STOP_LIMIT",
            getattr(self._mt5, "ORDER_TYPE_SELL_STOP_LIMIT", 7): "SELL_STOP_LIMIT",
        }
        return tuple(
            Mt5Order(
                ticket=str(row.ticket),
                symbol=str(row.symbol),
                side="BUY" if getattr(row, "type", None) in buy_types else "SELL",
                order_type=names.get(getattr(row, "type", None), str(getattr(row, "type", ""))),
                volume=Decimal(str(row.volume_current or row.volume_initial)),
                price_open=Decimal(str(row.price_open)),
                stop_loss=Decimal(str(row.sl)) if getattr(row, "sl", 0) else None,
                take_profit=Decimal(str(row.tp)) if getattr(row, "tp", 0) else None,
                magic=int(getattr(row, "magic", 0) or 0),
                comment=str(getattr(row, "comment", "") or ""),
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
        symbol = self._resolve_symbol(proposal.symbol)
        permissions = self.terminal_permissions()
        if permissions["terminal_trade_allowed"] is False:
            raise Mt5AdapterError("MT5 terminal AutoTrading is disabled: terminal_info.trade_allowed=False. Enable Algo Trading in MT5, then retry.")
        if permissions["account_trade_allowed"] is False or permissions["account_trade_expert"] is False:
            raise Mt5AdapterError("MT5 account does not allow expert trading")
        tick = self.get_tick(symbol)
        order_type = self._mt5.ORDER_TYPE_BUY if proposal.side is Side.BUY else self._mt5.ORDER_TYPE_SELL
        price = tick.ask if proposal.side is Side.BUY else tick.bid
        base_request = {"action": self._mt5.TRADE_ACTION_DEAL, "symbol": symbol, "volume": float(proposal.volume), "type": order_type, "price": float(price), "sl": float(proposal.stop_loss), "tp": float(proposal.take_profit), "deviation": 50, "magic": 260713, "comment": f"xau:{idempotency_key[:20]}", "type_time": self._mt5.ORDER_TIME_GTC}
        filling_modes = [self._mt5.ORDER_FILLING_IOC, self._mt5.ORDER_FILLING_FOK, self._mt5.ORDER_FILLING_RETURN]
        result = None
        for filling in filling_modes:
            result = self._mt5.order_send({**base_request, "type_filling": filling})
            if result is not None and result.retcode == self._mt5.TRADE_RETCODE_DONE:
                break
            comment = str(getattr(result, "comment", "")).lower() if result is not None else ""
            if "unsupported filling" not in comment and "invalid filling" not in comment:
                break
        if result is None or result.retcode != self._mt5.TRADE_RETCODE_DONE:
            raise Mt5AdapterError(f"MT5 order rejected: retcode={getattr(result, 'retcode', 'none')} comment={getattr(result, 'comment', 'no result')}")
        ticket = str(result.order or result.deal)
        self._orders[idempotency_key] = ticket
        return ticket

    def submit_pending_order(self, proposal: TradeProposal, order_type: str, comment: str, expires_at: datetime) -> str:
        if not self._allow_orders or self._kill_switch(): raise ExecutionDisabledError("MT5 kill switch or order gate is active")
        symbol = self._resolve_symbol(proposal.symbol)
        permissions = self.terminal_permissions()
        if permissions["terminal_trade_allowed"] is False:
            raise Mt5AdapterError("MT5 terminal AutoTrading is disabled: terminal_info.trade_allowed=False. Enable Algo Trading in MT5, then retry.")
        if permissions["account_trade_allowed"] is False or permissions["account_trade_expert"] is False:
            raise Mt5AdapterError("MT5 account does not allow expert trading")
        order_map = {
            "BUY_STOP": self._mt5.ORDER_TYPE_BUY_STOP,
            "SELL_STOP": self._mt5.ORDER_TYPE_SELL_STOP,
        }
        if order_type not in order_map:
            raise Mt5AdapterError(f"Unsupported pending order type: {order_type}")
        request = {
            "action": self._mt5.TRADE_ACTION_PENDING,
            "symbol": symbol,
            "volume": float(proposal.volume),
            "type": order_map[order_type],
            "price": float(proposal.entry_price),
            "sl": float(proposal.stop_loss),
            "tp": float(proposal.take_profit),
            "deviation": 50,
            "magic": 260713,
            "comment": comment[:31],
        }
        accepted = {
            self._mt5.TRADE_RETCODE_DONE,
            getattr(self._mt5, "TRADE_RETCODE_PLACED", self._mt5.TRADE_RETCODE_DONE),
        }
        result = None
        time_modes = (
            {
                "type_time": self._mt5.ORDER_TIME_SPECIFIED,
                "expiration": int(expires_at.timestamp()),
            },
            {"type_time": self._mt5.ORDER_TIME_GTC},
        )
        for time_mode in time_modes:
            for filling in (self._mt5.ORDER_FILLING_RETURN, self._mt5.ORDER_FILLING_IOC, self._mt5.ORDER_FILLING_FOK):
                result = self._mt5.order_send({**request, **time_mode, "type_filling": filling})
                if result is not None and result.retcode in accepted:
                    return str(result.order or result.deal)
                comment_text = str(getattr(result, "comment", "")).lower() if result is not None else ""
                if "unsupported filling" not in comment_text and "invalid filling" not in comment_text:
                    break
            if result is None or getattr(result, "retcode", None) != 10022:
                break
        raise Mt5AdapterError(f"MT5 pending order rejected: retcode={getattr(result, 'retcode', 'none')} comment={getattr(result, 'comment', 'no result')} last_error={self._mt5.last_error()}")

    def cancel_order(self, order: Mt5Order, comment: str) -> str:
        if not self._allow_orders or self._kill_switch(): raise ExecutionDisabledError("MT5 kill switch or order gate is active")
        request = {
            "action": self._mt5.TRADE_ACTION_REMOVE,
            "order": int(order.ticket),
            "symbol": order.symbol,
            "magic": 260713,
            "comment": "xaucancel",
        }
        result = self._mt5.order_send(request)
        if result is None or result.retcode != self._mt5.TRADE_RETCODE_DONE:
            raise Mt5AdapterError(f"MT5 pending cancel rejected: retcode={getattr(result, 'retcode', 'none')} comment={getattr(result, 'comment', 'no result')} last_error={self._mt5.last_error()}")
        return str(result.order or result.deal or order.ticket)

    def close_position(self, position: Mt5Position, comment: str) -> str:
        if not self._allow_orders or self._kill_switch(): raise ExecutionDisabledError("MT5 kill switch or order gate is active")
        permissions = self.terminal_permissions()
        if permissions["terminal_trade_allowed"] is False:
            raise Mt5AdapterError("MT5 terminal AutoTrading is disabled: terminal_info.trade_allowed=False. Enable Algo Trading in MT5, then retry.")
        symbol = self._resolve_symbol(position.symbol)
        tick = self.get_tick(symbol)
        is_buy_position = position.side == "BUY"
        order_type = self._mt5.ORDER_TYPE_SELL if is_buy_position else self._mt5.ORDER_TYPE_BUY
        price = tick.bid if is_buy_position else tick.ask
        base_request = {
            "action": self._mt5.TRADE_ACTION_DEAL, "position": int(position.ticket),
            "symbol": symbol, "volume": float(position.volume), "type": order_type,
            "price": float(price), "deviation": 50, "magic": 260713,
            "comment": "xauclose", "type_time": self._mt5.ORDER_TIME_GTC,
        }
        result = None
        for filling in (self._mt5.ORDER_FILLING_IOC, self._mt5.ORDER_FILLING_FOK, self._mt5.ORDER_FILLING_RETURN):
            request = {**base_request, "type_filling": filling}
            for _ in range(3):
                result = self._mt5.order_send(request)
                if result is not None:
                    break
                time.sleep(0.5)
            if result is not None and result.retcode == self._mt5.TRADE_RETCODE_DONE: break
            comment_text = str(getattr(result, "comment", "")).lower() if result is not None else ""
            if "unsupported filling" not in comment_text and "invalid filling" not in comment_text:
                break
        if result is None or result.retcode != self._mt5.TRADE_RETCODE_DONE:
            raise Mt5AdapterError(f"MT5 close rejected: retcode={getattr(result, 'retcode', 'none')} comment={getattr(result, 'comment', 'no result')} last_error={self._mt5.last_error()}")
        return str(result.order or result.deal)

    def modify_position_protection(self, position: Mt5Position, stop_loss: Decimal | None, take_profit: Decimal | None, comment: str) -> Mt5Position:
        if not self._allow_orders or self._kill_switch(): raise ExecutionDisabledError("MT5 kill switch or order gate is active")
        symbol = self._resolve_symbol(position.symbol)
        info = self._mt5.symbol_info(symbol)
        if info is None:
            raise Mt5AdapterError(f"Unable to inspect symbol: {position.symbol}")
        digits = int(getattr(info, "digits", 2) or 2)
        current_sl = position.stop_loss
        if stop_loss is not None:
            stop_loss = Decimal(str(round(float(stop_loss), digits)))
            if current_sl is not None:
                if position.side == "BUY" and stop_loss < current_sl:
                    raise Mt5AdapterError("Refusing to loosen BUY protective stop")
                if position.side == "SELL" and stop_loss > current_sl:
                    raise Mt5AdapterError("Refusing to loosen SELL protective stop")
        if take_profit is not None:
            take_profit = Decimal(str(round(float(take_profit), digits)))
        request = {
            "action": self._mt5.TRADE_ACTION_SLTP,
            "position": int(position.ticket),
            "symbol": symbol,
            "sl": float(stop_loss if stop_loss is not None else position.stop_loss or 0),
            "tp": float(take_profit if take_profit is not None else position.take_profit or 0),
        }
        result = self._mt5.order_send(request)
        if result is None or result.retcode != self._mt5.TRADE_RETCODE_DONE:
            raise Mt5AdapterError(f"MT5 SLTP rejected: retcode={getattr(result, 'retcode', 'none')} comment={getattr(result, 'comment', 'no result')} last_error={self._mt5.last_error()}")
        for _ in range(3):
            confirmed = next((open_position for open_position in self.get_positions(symbol) if open_position.ticket == position.ticket), None)
            if confirmed is None:
                raise Mt5AdapterError("Position disappeared while confirming SL/TP modification")
            sl_ok = stop_loss is None or confirmed.stop_loss == stop_loss
            tp_ok = take_profit is None or confirmed.take_profit == take_profit
            if sl_ok and tp_ok:
                return confirmed
            time.sleep(0.5)
        raise Mt5AdapterError("MT5 SL/TP modification was sent but not visible on the position")


@dataclass
class MockMt5Gateway:
    account: AccountSnapshot
    symbol_specification: object = object()
    enabled: bool = False
    positions: tuple[Mt5Position, ...] = ()
    orders: tuple[Mt5Order, ...] = ()
    fills: tuple[Mt5Fill, ...] = ()
    _orders: dict[str, str] = field(default_factory=dict)
    def get_account_snapshot(self) -> AccountSnapshot: return self.account
    def get_symbol_specification(self, symbol: str) -> object: return self.symbol_specification
    def get_tick(self, symbol: str) -> Mt5Tick: return Mt5Tick(symbol, Decimal("2300"), Decimal("2300.5"), 0)
    def get_positions(self, symbol: str | None = None) -> tuple[Mt5Position, ...]:
        return tuple(position for position in self.positions if symbol is None or position.symbol == symbol)
    def get_orders(self, symbol: str | None = None) -> tuple[Mt5Order, ...]:
        return tuple(order for order in self.orders if symbol is None or order.symbol == symbol)
    def get_recent_fills(self, since: datetime, until: datetime | None = None) -> tuple[Mt5Fill, ...]:
        return tuple(fill for fill in self.fills if fill.filled_at >= since and (until is None or fill.filled_at <= until))
    def submit_approved_trade(self, proposal: TradeProposal, idempotency_key: str) -> str:
        if not self.enabled: raise ExecutionDisabledError("Mock execution is disabled")
        return self._orders.setdefault(idempotency_key, f"demo-order-{len(self._orders) + 1}")
    def close_position(self, position: Mt5Position, comment: str) -> str:
        if not self.enabled: raise ExecutionDisabledError("Mock execution is disabled")
        return f"demo-close-{position.ticket}"
    def submit_pending_order(self, proposal: TradeProposal, order_type: str, comment: str, expires_at: datetime) -> str:
        if not self.enabled: raise ExecutionDisabledError("Mock execution is disabled")
        ticket = f"demo-{order_type.lower()}-{len(self.orders) + 1}"
        self.orders = (
            *self.orders,
            Mt5Order(
                ticket=ticket,
                symbol=proposal.symbol,
                side=proposal.side.value,
                order_type=order_type,
                volume=proposal.volume,
                price_open=proposal.entry_price,
                stop_loss=proposal.stop_loss,
                take_profit=proposal.take_profit,
                magic=260713,
                comment=comment,
            ),
        )
        return ticket
    def cancel_order(self, order: Mt5Order, comment: str) -> str:
        if not self.enabled: raise ExecutionDisabledError("Mock execution is disabled")
        self.orders = tuple(open_order for open_order in self.orders if open_order.ticket != order.ticket)
        return f"demo-cancel-{order.ticket}"
    def modify_position_protection(self, position: Mt5Position, stop_loss: Decimal | None, take_profit: Decimal | None, comment: str) -> Mt5Position:
        if not self.enabled: raise ExecutionDisabledError("Mock execution is disabled")
        updated = Mt5Position(
            ticket=position.ticket, symbol=position.symbol, side=position.side, volume=position.volume,
            price_open=position.price_open, stop_loss=stop_loss if stop_loss is not None else position.stop_loss,
            take_profit=take_profit if take_profit is not None else position.take_profit,
            profit=position.profit, opened_at=position.opened_at,
        )
        self.positions = tuple(updated if open_position.ticket == position.ticket else open_position for open_position in self.positions)
        return updated
