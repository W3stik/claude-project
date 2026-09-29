"""Alpaca trading API (paper or live). US stocks/ETFs with bracket orders, plus crypto."""

from __future__ import annotations

from datetime import datetime
from typing import Any

import httpx
import pandas as pd

from ..alpaca_common import TRADING_URL_LIVE, TRADING_URL_PAPER, AlpacaHTTP, alpaca_symbol, rfc3339
from ..models import Account, Fill, Order, OrderRequest, OrderStatus, OrderType, Position, Side
from ..sessions import is_crypto_symbol
from .base import Broker, BrokerError

STATUS_MAP = {
    "new": OrderStatus.NEW,
    "accepted": OrderStatus.NEW,
    "pending_new": OrderStatus.NEW,
    "accepted_for_bidding": OrderStatus.NEW,
    "held": OrderStatus.NEW,
    "calculated": OrderStatus.NEW,
    "pending_cancel": OrderStatus.NEW,
    "pending_replace": OrderStatus.NEW,
    "partially_filled": OrderStatus.PARTIALLY_FILLED,
    "filled": OrderStatus.FILLED,
    "done_for_day": OrderStatus.EXPIRED,
    "expired": OrderStatus.EXPIRED,
    "canceled": OrderStatus.CANCELED,
    "replaced": OrderStatus.CANCELED,
    "stopped": OrderStatus.FILLED,
    "rejected": OrderStatus.REJECTED,
    "suspended": OrderStatus.REJECTED,
}

TYPE_MAP = {
    "market": OrderType.MARKET,
    "limit": OrderType.LIMIT,
    "stop": OrderType.STOP,
    "stop_limit": OrderType.STOP,
    "trailing_stop": OrderType.STOP,
}


def round_price(price: float) -> float:
    """Alpaca rejects sub-penny prices: 2 decimals from $1, otherwise 4."""
    return round(price, 2) if price >= 1 else round(price, 4)


def decimal_str(value: float) -> str:
    """Plain decimal string (never scientific notation) as the Alpaca API expects."""
    if float(value).is_integer():
        return str(int(value))
    return f"{value:.9f}".rstrip("0").rstrip(".")


def _float(value: Any) -> float | None:
    return float(value) if value not in (None, "") else None


def _dt(value: Any) -> datetime | None:
    return pd.Timestamp(value).to_pydatetime() if value else None


class AlpacaBroker(Broker):
    name = "alpaca"
    supports_bracket = True
    supports_short = True
    fractional = False

    def __init__(self, api_key: str, secret_key: str, paper: bool = True, client: httpx.Client | None = None) -> None:
        base_url = TRADING_URL_PAPER if paper else TRADING_URL_LIVE
        self.http = AlpacaHTTP(base_url, api_key, secret_key, client=client, error_cls=BrokerError)
        self.paper = paper
        self.is_live = not paper

    # -- account ---------------------------------------------------------------------
    def get_account(self) -> Account:
        data = self.http.request("GET", "/v2/account")
        return Account(
            equity=float(data["equity"]),
            cash=float(data["cash"]),
            buying_power=float(data["buying_power"]),
            currency=data.get("currency", "USD"),
            day_start_equity=_float(data.get("last_equity")),
            pattern_day_trader=data.get("pattern_day_trader"),
            day_trade_count=int(data["daytrade_count"]) if data.get("daytrade_count") is not None else None,
            is_live=self.is_live,
            extra={k: data.get(k) for k in ("status", "trading_blocked", "account_blocked", "shorting_enabled")},
        )

    def get_positions(self) -> list[Position]:
        positions = []
        for item in self.http.request("GET", "/v2/positions") or []:
            qty = abs(float(item["qty"]))
            if item.get("side") == "short":
                qty = -qty
            positions.append(
                Position(
                    symbol=item["symbol"],
                    qty=qty,
                    avg_price=float(item["avg_entry_price"]),
                    current_price=_float(item.get("current_price")),
                )
            )
        return positions

    def is_market_open(self) -> bool | None:
        clock = self.http.request("GET", "/v2/clock")
        return bool(clock.get("is_open")) if clock else None

    # -- orders --------------------------------------------------------------------------
    # Alpaca has no bracket/OTO orders and no short selling for crypto.
    def supports_bracket_for(self, symbol: str) -> bool:
        return self.supports_bracket and not is_crypto_symbol(symbol)

    def supports_short_for(self, symbol: str) -> bool:
        return self.supports_short and not is_crypto_symbol(symbol)

    def build_order_payload(self, request: OrderRequest) -> dict[str, Any]:
        crypto = is_crypto_symbol(request.symbol)
        payload: dict[str, Any] = {
            "symbol": request.symbol.upper(),
            "qty": decimal_str(request.qty),
            "side": request.side.value,
            "type": request.type.value,
            "time_in_force": "gtc" if crypto else request.time_in_force.value,
        }
        if request.limit_price is not None:
            payload["limit_price"] = decimal_str(round_price(request.limit_price))
        if request.stop_price is not None:
            payload["stop_price"] = decimal_str(round_price(request.stop_price))
        if request.client_order_id:
            payload["client_order_id"] = request.client_order_id
        has_sl, has_tp = request.stop_loss is not None, request.take_profit is not None
        if (has_sl or has_tp) and not crypto:
            payload["order_class"] = "bracket" if has_sl and has_tp else "oto"
            if has_sl:
                payload["stop_loss"] = {"stop_price": decimal_str(round_price(request.stop_loss))}
            if has_tp:
                payload["take_profit"] = {"limit_price": decimal_str(round_price(request.take_profit))}
        return payload

    def submit_order(self, request: OrderRequest) -> Order:
        try:
            request.validate()
        except ValueError as exc:
            raise BrokerError(str(exc)) from exc
        if is_crypto_symbol(request.symbol) and (request.stop_loss or request.take_profit):
            raise BrokerError("Alpaca nepodporuje bracket příkazy pro krypto – stop-loss zadej samostatně.")
        data = self.http.request("POST", "/v2/orders", json=self.build_order_payload(request))
        return self._parse_order(data)

    def cancel_order(self, order_id: str, symbol: str | None = None) -> None:
        self.http.request("DELETE", f"/v2/orders/{order_id}")

    def get_orders(self, status: str = "open", limit: int = 100) -> list[Order]:
        data = self.http.request(
            "GET", "/v2/orders", params={"status": status, "limit": limit, "nested": "true", "direction": "desc"}
        )
        orders: list[Order] = []
        for item in data or []:
            orders.append(self._parse_order(item))
            for leg in item.get("legs") or []:
                orders.append(self._parse_order(leg, parent_id=item.get("id")))
        if status == "open":
            orders = [o for o in orders if o.status.is_open]
        return orders

    def close_position(self, symbol: str) -> Order | None:
        key = alpaca_symbol(symbol).upper()
        position = next((p for p in self.get_positions() if alpaca_symbol(p.symbol).upper() == key), None)
        if position is None:
            return None
        # Bracket legs hold the shares; cancel them first or the closing order is rejected.
        for order in self.get_orders("open"):
            if alpaca_symbol(order.symbol).upper() == key:
                try:
                    self.cancel_order(order.id)
                except BrokerError:
                    pass  # OCO sibling already cancelled together with its pair
        data = self.http.request("DELETE", f"/v2/positions/{key}")
        return self._parse_order(data) if data else None

    def close_all(self) -> list[Order]:
        data = self.http.request("DELETE", "/v2/positions", params={"cancel_orders": "true"})
        orders = []
        for item in data or []:
            body = item.get("body") if isinstance(item, dict) else None
            if isinstance(body, dict) and body.get("id"):
                orders.append(self._parse_order(body))
        return orders

    def get_fills(self, since: datetime | None = None) -> list[Fill]:
        params: dict[str, Any] = {"direction": "asc", "page_size": 100}
        if since is not None:
            params["after"] = rfc3339(since)
        fills: list[Fill] = []
        for _ in range(50):
            data = self.http.request("GET", "/v2/account/activities/FILL", params=params) or []
            for item in data:
                side = Side.BUY if item.get("side") == "buy" else Side.SELL  # "sell_short" -> SELL
                fills.append(
                    Fill(
                        id=item["id"],
                        order_id=item.get("order_id"),
                        symbol=item["symbol"],
                        side=side,
                        qty=float(item["qty"]),
                        price=float(item["price"]),
                        timestamp=_dt(item.get("transaction_time")),
                    )
                )
            if len(data) < params["page_size"]:
                break
            params["page_token"] = data[-1]["id"]
        return fills

    @staticmethod
    def _parse_order(data: dict[str, Any], parent_id: str | None = None) -> Order:
        return Order(
            id=data["id"],
            symbol=data["symbol"],
            side=Side.BUY if data.get("side") == "buy" else Side.SELL,
            qty=float(data.get("qty") or data.get("filled_qty") or 0),
            type=TYPE_MAP.get(data.get("type") or data.get("order_type"), OrderType.MARKET),
            status=STATUS_MAP.get(data.get("status", "new"), OrderStatus.NEW),
            limit_price=_float(data.get("limit_price")),
            stop_price=_float(data.get("stop_price")),
            filled_qty=float(data.get("filled_qty") or 0),
            filled_avg_price=_float(data.get("filled_avg_price")),
            created_at=_dt(data.get("created_at") or data.get("submitted_at")),
            filled_at=_dt(data.get("filled_at")),
            client_order_id=data.get("client_order_id"),
            parent_id=parent_id,
            time_in_force=data.get("time_in_force", "day"),
            raw=data,
        )
