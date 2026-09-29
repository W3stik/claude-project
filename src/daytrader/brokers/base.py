"""Broker interface: account, positions, orders and fills."""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime

from ..models import Account, Fill, Order, OrderRequest, OrderType, Position, Side


class BrokerError(RuntimeError):
    """The broker rejected a request or could not be reached."""


class Broker(ABC):
    name: str = "base"
    #: True when orders move real money.
    is_live: bool = False
    #: Broker attaches stop-loss/take-profit legs to an entry order server-side.
    supports_bracket: bool = False
    supports_short: bool = False
    fractional: bool = False

    @abstractmethod
    def get_account(self) -> Account: ...

    @abstractmethod
    def get_positions(self) -> list[Position]: ...

    def get_position(self, symbol: str) -> Position | None:
        symbol = symbol.upper()
        for position in self.get_positions():
            if position.symbol.upper() == symbol:
                return position
        return None

    @abstractmethod
    def submit_order(self, request: OrderRequest) -> Order: ...

    @abstractmethod
    def cancel_order(self, order_id: str, symbol: str | None = None) -> None: ...

    @abstractmethod
    def get_orders(self, status: str = "open", limit: int = 100) -> list[Order]:
        """``status`` is ``open``, ``closed`` or ``all``."""

    @abstractmethod
    def get_fills(self, since: datetime | None = None) -> list[Fill]: ...

    def close_position(self, symbol: str) -> Order | None:
        """Cancel the symbol's open orders and flatten the position with a market order."""
        for order in self.get_orders("open"):
            if order.symbol.upper() == symbol.upper():
                try:
                    self.cancel_order(order.id, order.symbol)
                except BrokerError:
                    pass  # already filled/cancelled in the meantime
        position = self.get_position(symbol)
        if position is None or position.qty == 0:
            return None
        side = Side.SELL if position.qty > 0 else Side.BUY
        return self.submit_order(
            OrderRequest(symbol=position.symbol, side=side, qty=abs(position.qty), type=OrderType.MARKET)
        )

    def close_all(self) -> list[Order]:
        closed = []
        for position in self.get_positions():
            order = self.close_position(position.symbol)
            if order is not None:
                closed.append(order)
        return closed

    @property
    def account_key(self) -> str:
        """Identifies the trading account (one bot per account)."""
        return f"{self.name}:{'live' if self.is_live else 'paper'}"

    def sync(self) -> None:
        """Process pending simulated orders (paper broker); no-op for real brokers."""

    def is_market_open(self) -> bool | None:
        """``None`` when the broker cannot tell."""
        return None
