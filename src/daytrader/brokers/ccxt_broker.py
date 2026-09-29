"""Spot trading on crypto exchanges through CCXT (Binance, Kraken, Coinbase, Coinmate, ...).

Spot accounts cannot short and CCXT has no exchange-independent bracket orders, so the
trading bot watches stop-loss / take-profit levels itself for this broker.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import pandas as pd

from ..data.ccxt_provider import normalize_pair
from ..models import Account, Fill, Order, OrderRequest, OrderStatus, OrderType, Position, Side
from .base import Broker, BrokerError

STATUS_MAP = {
    "open": OrderStatus.NEW,
    "closed": OrderStatus.FILLED,
    "canceled": OrderStatus.CANCELED,
    "cancelled": OrderStatus.CANCELED,
    "expired": OrderStatus.EXPIRED,
    "rejected": OrderStatus.REJECTED,
}


def _ms_to_dt(value: Any) -> datetime | None:
    return pd.Timestamp(int(value), unit="ms", tz="UTC").to_pydatetime() if value else None


class CCXTBroker(Broker):
    name = "ccxt"
    supports_bracket = False
    supports_short = False
    fractional = True

    def __init__(
        self,
        exchange: Any,
        quote_currency: str = "USDT",
        sandbox: bool = True,
        symbols: list[str] | None = None,
        min_position_value: float = 1.0,
    ) -> None:
        self.exchange = exchange
        self.quote = quote_currency.upper()
        self.is_live = not sandbox
        self.symbols = [normalize_pair(s) for s in (symbols or []) if "/" in s or "-" in s]
        self.min_position_value = min_position_value
        self._markets: dict[str, Any] | None = None

    def _call(self, method: str, *args: Any, **kwargs: Any) -> Any:
        try:
            return getattr(self.exchange, method)(*args, **kwargs)
        except BrokerError:
            raise
        except Exception as exc:
            raise BrokerError(f"{self.exchange.id}: {method} selhalo: {exc}") from exc

    def _market_ids(self) -> dict[str, Any]:
        if self._markets is None:
            self._markets = self._call("load_markets") or {}
        return self._markets

    def _price(self, pair: str) -> float | None:
        if pair not in self._market_ids():
            return None
        try:
            ticker = self.exchange.fetch_ticker(pair)
        except Exception:
            return None
        price = ticker.get("last") or ticker.get("close")
        return float(price) if price else None

    # -- account ---------------------------------------------------------------------
    def get_account(self) -> Account:
        balance = self._call("fetch_balance")
        totals = balance.get("total") or {}
        free = balance.get("free") or {}
        cash = float(totals.get(self.quote) or 0.0)
        equity = cash
        for asset, amount in totals.items():
            if asset == self.quote or not amount:
                continue
            price = self._price(f"{asset}/{self.quote}")
            if price:
                equity += float(amount) * price
        return Account(
            equity=equity,
            cash=cash,
            buying_power=float(free.get(self.quote) or 0.0),
            currency=self.quote,
            is_live=self.is_live,
        )

    def get_positions(self) -> list[Position]:
        balance = self._call("fetch_balance")
        positions = []
        for asset, amount in (balance.get("total") or {}).items():
            if asset == self.quote or not amount:
                continue
            pair = f"{asset}/{self.quote}"
            price = self._price(pair)
            if price is None or float(amount) * price < self.min_position_value:
                continue
            avg = self._average_entry(pair) or price
            positions.append(Position(symbol=pair, qty=float(amount), avg_price=avg, current_price=price))
        return positions

    def _average_entry(self, pair: str) -> float | None:
        """FIFO average cost of the currently held amount, from recent own trades."""
        try:
            trades = self.exchange.fetch_my_trades(pair, limit=200)
        except Exception:
            return None
        lots: list[list[float]] = []
        for trade in sorted(trades, key=lambda t: t.get("timestamp") or 0):
            qty, price = float(trade["amount"]), float(trade["price"])
            if trade.get("side") == "buy":
                lots.append([qty, price])
                continue
            while qty > 1e-12 and lots:
                take = min(qty, lots[0][0])
                lots[0][0] -= take
                qty -= take
                if lots[0][0] <= 1e-12:
                    lots.pop(0)
        held = sum(q for q, _ in lots)
        return sum(q * p for q, p in lots) / held if held > 0 else None

    # -- orders ------------------------------------------------------------------------
    def submit_order(self, request: OrderRequest) -> Order:
        try:
            request.validate()
        except ValueError as exc:
            raise BrokerError(str(exc)) from exc
        if request.type is OrderType.STOP:
            raise BrokerError("Stop příkazy nejsou přes CCXT jednotně podporované – stop hlídá bot.")
        pair = normalize_pair(request.symbol)
        if pair not in self._market_ids():
            raise BrokerError(f"{self.exchange.id} nemá trh {pair}.")
        if request.side is Side.SELL:
            position = self.get_position(pair)
            if position is None or position.qty < request.qty * 0.999:
                raise BrokerError("Na spotovém účtu nelze prodat víc, než držíš (shortování není možné).")
        amount = float(self.exchange.amount_to_precision(pair, request.qty))
        price = None
        if request.type is OrderType.LIMIT:
            price = float(self.exchange.price_to_precision(pair, request.limit_price))
        params = {"clientOrderId": request.client_order_id} if request.client_order_id else {}
        data = self._call("create_order", pair, request.type.value, request.side.value, amount, price, params)
        return self._parse_order(data)

    def cancel_order(self, order_id: str, symbol: str | None = None) -> None:
        self._call("cancel_order", order_id, normalize_pair(symbol) if symbol else None)

    def _tracked_pairs(self) -> list[str]:
        pairs = set(self.symbols)
        try:
            pairs.update(p.symbol for p in self.get_positions())
        except BrokerError:
            pass
        return sorted(pairs)

    def get_orders(self, status: str = "open", limit: int = 100) -> list[Order]:
        raw: list[dict[str, Any]] = []
        if status in ("open", "all"):
            try:
                raw.extend(self.exchange.fetch_open_orders())
            except Exception:
                for pair in self._tracked_pairs():
                    raw.extend(self._call("fetch_open_orders", pair))
        if status in ("closed", "all"):
            for pair in self._tracked_pairs():
                raw.extend(self._call("fetch_closed_orders", pair, None, limit))
        orders = [self._parse_order(item) for item in raw]
        orders.sort(key=lambda o: o.created_at or datetime.min.replace(tzinfo=timezone.utc), reverse=True)
        return orders[:limit]

    def get_fills(self, since: datetime | None = None) -> list[Fill]:
        since_ms = int(pd.Timestamp(since).timestamp() * 1000) if since is not None else None
        fills: list[Fill] = []
        for pair in self._tracked_pairs():
            for trade in self._call("fetch_my_trades", pair, since_ms):
                fee = trade.get("fee") or {}
                fills.append(
                    Fill(
                        id=str(trade["id"]),
                        order_id=trade.get("order"),
                        symbol=trade["symbol"],
                        side=Side(trade["side"]),
                        qty=float(trade["amount"]),
                        price=float(trade["price"]),
                        timestamp=_ms_to_dt(trade.get("timestamp")),
                        commission=float(fee.get("cost") or 0.0) if fee.get("currency") == self.quote else 0.0,
                    )
                )
        fills.sort(key=lambda f: f.timestamp)
        return fills

    @staticmethod
    def _parse_order(data: dict[str, Any]) -> Order:
        order_type = OrderType.LIMIT if data.get("type") == "limit" else OrderType.MARKET
        return Order(
            id=str(data.get("id")),
            symbol=data.get("symbol", ""),
            side=Side(data.get("side", "buy")),
            qty=float(data.get("amount") or 0.0),
            type=order_type,
            status=STATUS_MAP.get(data.get("status") or "open", OrderStatus.NEW),
            limit_price=float(data["price"]) if order_type is OrderType.LIMIT and data.get("price") else None,
            filled_qty=float(data.get("filled") or 0.0),
            filled_avg_price=float(data["average"]) if data.get("average") else None,
            created_at=_ms_to_dt(data.get("timestamp")),
            client_order_id=data.get("clientOrderId"),
            raw=data,
        )
