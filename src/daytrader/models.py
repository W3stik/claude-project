"""Broker-independent domain objects shared by data providers, brokers and the UI."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any


class Side(str, Enum):
    BUY = "buy"
    SELL = "sell"

    @property
    def sign(self) -> int:
        return 1 if self is Side.BUY else -1

    def opposite(self) -> "Side":
        return Side.SELL if self is Side.BUY else Side.BUY


class OrderType(str, Enum):
    MARKET = "market"
    LIMIT = "limit"
    STOP = "stop"


class OrderStatus(str, Enum):
    NEW = "new"
    PARTIALLY_FILLED = "partially_filled"
    FILLED = "filled"
    CANCELED = "canceled"
    REJECTED = "rejected"
    EXPIRED = "expired"

    @property
    def is_open(self) -> bool:
        return self in (OrderStatus.NEW, OrderStatus.PARTIALLY_FILLED)


class TimeInForce(str, Enum):
    DAY = "day"
    GTC = "gtc"


@dataclass
class OrderRequest:
    """What we want the broker to do.

    ``stop_loss`` / ``take_profit`` turn the order into a bracket (OCO exit legs are
    attached once the entry fills) on brokers that support it.
    """

    symbol: str
    side: Side
    qty: float
    type: OrderType = OrderType.MARKET
    limit_price: float | None = None
    stop_price: float | None = None
    time_in_force: TimeInForce = TimeInForce.DAY
    stop_loss: float | None = None
    take_profit: float | None = None
    client_order_id: str | None = None

    def validate(self) -> None:
        if not self.symbol:
            raise ValueError("Chybí symbol.")
        if self.qty is None or self.qty <= 0:
            raise ValueError("Množství musí být kladné.")
        if self.type is OrderType.LIMIT and not self.limit_price:
            raise ValueError("Limitní příkaz potřebuje limitní cenu.")
        if self.type is OrderType.STOP and not self.stop_price:
            raise ValueError("Stop příkaz potřebuje stop cenu.")
        ref = self.limit_price or self.stop_price
        if ref and self.stop_loss:
            if self.side is Side.BUY and self.stop_loss >= ref:
                raise ValueError("Stop-loss nákupu musí být pod vstupní cenou.")
            if self.side is Side.SELL and self.stop_loss <= ref:
                raise ValueError("Stop-loss prodeje (shortu) musí být nad vstupní cenou.")
        if ref and self.take_profit:
            if self.side is Side.BUY and self.take_profit <= ref:
                raise ValueError("Take-profit nákupu musí být nad vstupní cenou.")
            if self.side is Side.SELL and self.take_profit >= ref:
                raise ValueError("Take-profit prodeje (shortu) musí být pod vstupní cenou.")


@dataclass
class Order:
    id: str
    symbol: str
    side: Side
    qty: float
    type: OrderType
    status: OrderStatus
    limit_price: float | None = None
    stop_price: float | None = None
    filled_qty: float = 0.0
    filled_avg_price: float | None = None
    created_at: datetime | None = None
    filled_at: datetime | None = None
    client_order_id: str | None = None
    parent_id: str | None = None
    time_in_force: str = "day"
    raw: dict[str, Any] = field(default_factory=dict, repr=False)

    def to_row(self) -> dict[str, Any]:
        row = asdict(self)
        row.pop("raw", None)
        row["side"] = self.side.value
        row["type"] = self.type.value
        row["status"] = self.status.value
        return row


@dataclass
class Position:
    symbol: str
    qty: float  # signed: > 0 long, < 0 short
    avg_price: float
    current_price: float | None = None

    @property
    def side(self) -> str:
        return "long" if self.qty > 0 else "short"

    @property
    def market_value(self) -> float | None:
        if self.current_price is None:
            return None
        return self.qty * self.current_price

    @property
    def unrealized_pnl(self) -> float | None:
        if self.current_price is None or not self.avg_price:
            return None
        return (self.current_price - self.avg_price) * self.qty

    @property
    def unrealized_pnl_pct(self) -> float | None:
        pnl = self.unrealized_pnl
        if pnl is None or not self.avg_price:
            return None
        return pnl / (abs(self.qty) * self.avg_price) * 100

    def to_row(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "side": self.side,
            "qty": self.qty,
            "avg_price": self.avg_price,
            "current_price": self.current_price,
            "market_value": self.market_value,
            "unrealized_pnl": self.unrealized_pnl,
            "unrealized_pnl_pct": self.unrealized_pnl_pct,
        }


@dataclass
class Account:
    equity: float
    cash: float
    buying_power: float
    currency: str = "USD"
    day_start_equity: float | None = None
    pattern_day_trader: bool | None = None
    day_trade_count: int | None = None
    is_live: bool = False
    extra: dict[str, Any] = field(default_factory=dict, repr=False)

    @property
    def day_pnl(self) -> float | None:
        if self.day_start_equity is None:
            return None
        return self.equity - self.day_start_equity

    @property
    def day_pnl_pct(self) -> float | None:
        if not self.day_start_equity:
            return None
        return (self.equity / self.day_start_equity - 1) * 100


@dataclass
class Fill:
    id: str
    order_id: str | None
    symbol: str
    side: Side
    qty: float
    price: float
    timestamp: datetime
    commission: float = 0.0

    def to_row(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "order_id": self.order_id,
            "symbol": self.symbol,
            "side": self.side.value,
            "qty": self.qty,
            "price": self.price,
            "timestamp": self.timestamp,
            "commission": self.commission,
        }


@dataclass
class Quote:
    symbol: str
    price: float
    previous_close: float | None = None
    day_high: float | None = None
    day_low: float | None = None
    currency: str | None = None
    timestamp: datetime | None = None

    @property
    def change_pct(self) -> float | None:
        if not self.previous_close:
            return None
        return (self.price / self.previous_close - 1) * 100


@dataclass
class NewsItem:
    title: str
    source: str | None = None
    url: str | None = None
    published: datetime | None = None
    summary: str | None = None
