"""Manual order workflow shared by the CLI and the dashboard: plan (size + risk check)
first, show it to the trader, then execute."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone

import numpy as np

from .analysis.indicators import atr
from .brokers.base import Broker, BrokerError
from .data.base import DataError, DataProvider
from .journal import Journal
from .models import Order, OrderRequest, OrderType, Side
from .risk import RiskCheck, RiskManager
from .sessions import is_crypto_symbol


@dataclass
class OrderPlan:
    symbol: str
    side: Side
    qty: float
    entry: float
    order_type: OrderType
    limit_price: float | None
    stop: float | None
    target: float | None
    reduces_position: bool
    equity: float
    check: RiskCheck = field(default_factory=RiskCheck)
    notes: list[str] = field(default_factory=list)

    @property
    def notional(self) -> float:
        return self.qty * self.entry

    @property
    def risk_amount(self) -> float | None:
        return abs(self.entry - self.stop) * self.qty if self.stop is not None else None

    @property
    def risk_pct(self) -> float | None:
        amount = self.risk_amount
        return amount / self.equity * 100 if amount is not None and self.equity > 0 else None

    @property
    def reward_risk(self) -> float | None:
        if self.stop is None or self.target is None or self.entry == self.stop:
            return None
        return abs(self.target - self.entry) / abs(self.entry - self.stop)

    def summary_rows(self) -> list[tuple[str, str]]:
        rows = [
            ("Symbol", self.symbol),
            ("Směr", "NÁKUP (long)" if self.side is Side.BUY else "PRODEJ (short/uzavření)"),
            ("Typ", "limitní" if self.order_type is OrderType.LIMIT else "tržní"),
            ("Množství", f"{self.qty:g}"),
            ("Cena (odhad)", f"{self.entry:.4g}"),
            ("Hodnota pozice", f"{self.notional:,.2f}".replace(",", " ")),
        ]
        if self.stop is not None:
            rows.append(("Stop-loss", f"{self.stop:.4g}"))
        if self.target is not None:
            rows.append(("Take-profit", f"{self.target:.4g}"))
        if self.risk_amount is not None:
            rows.append(("Riziko", f"{self.risk_amount:,.2f} ({self.risk_pct:.2f} % kapitálu)".replace(",", " ")))
        if self.reward_risk is not None:
            rows.append(("Poměr zisk/riziko", f"{self.reward_risk:.2f} : 1"))
        return rows


def plan_order(
    broker: Broker,
    provider: DataProvider,
    risk: RiskManager,
    symbol: str,
    side: Side,
    qty: float | None = None,
    limit_price: float | None = None,
    stop: float | None = None,
    target: float | None = None,
    auto_levels: bool = True,
    journal: Journal | None = None,
) -> OrderPlan:
    symbol = symbol.upper()
    entry = limit_price or provider.get_latest_price(symbol)
    account = broker.get_account()
    positions = broker.get_positions()
    position = next((p for p in positions if p.symbol.upper().replace("/", "") == symbol.replace("/", "")), None)
    reduces = bool(position and np.sign(position.qty) == -side.sign and (qty is None or qty <= abs(position.qty)))
    notes: list[str] = []

    if reduces:
        qty = qty or abs(position.qty)
        stop = target = None
        check = RiskCheck()
        notes.append("Příkaz zmenšuje/uzavírá existující pozici – kontroly rizika nového obchodu se neaplikují.")
    else:
        if auto_levels and (stop is None or target is None):
            try:
                bars = provider.get_bars(symbol, interval="5m", period="5d")
                atr_value = float(atr(bars).iloc[-1])
            except (DataError, IndexError, ValueError):
                atr_value = float("nan")
            auto_stop, auto_target = risk.levels(side, entry, atr_value)
            if stop is None and auto_stop is not None:
                stop = round(auto_stop, 4)
                notes.append(f"Stop-loss dopočítán: {risk.config.stop_atr_mult:g}× ATR(14) z 5min svíček.")
            if target is None and auto_target is not None:
                target = round(auto_target, 4)
        fractional = broker.fractional or is_crypto_symbol(symbol)
        if qty is None:
            qty = risk.size(account.equity, entry, stop, fractional=fractional)
            notes.append(f"Množství dopočítáno z rizika {risk.config.risk_per_trade_pct:g} % kapitálu.")
            if stop is not None and entry != stop:
                by_risk = account.equity * risk.config.risk_per_trade_pct / 100 / abs(entry - stop)
                if qty < by_risk - 1:
                    notes.append(
                        f"Velikost omezena limitem {risk.config.max_position_pct:g} % kapitálu na jednu pozici "
                        "(stop je blízko, takže skutečné riziko je nižší než plánované)."
                    )
        trades_today = 0
        if journal is not None:
            start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
            trades_today = journal.entries_since(start, broker.name)
        check = risk.check_new_trade(account, positions, symbol, side, qty, entry, stop, trades_today)
        if (stop is not None or target is not None) and not broker.supports_bracket_for(symbol):
            notes.append(f"{broker.name} nepodporuje bracket příkazy – stop-loss/take-profit hlídej ručně nebo botem.")

    return OrderPlan(
        symbol=symbol,
        side=side,
        qty=float(qty or 0),
        entry=float(entry),
        order_type=OrderType.LIMIT if limit_price else OrderType.MARKET,
        limit_price=limit_price,
        stop=stop,
        target=target,
        reduces_position=reduces,
        equity=account.equity,
        check=check,
        notes=notes,
    )


def execute_plan(broker: Broker, plan: OrderPlan, journal: Journal | None = None, source: str = "manual") -> Order:
    if not plan.check.allowed:
        raise BrokerError("Příkaz neprošel kontrolou rizika: " + " ".join(plan.check.reasons))
    if plan.qty <= 0:
        raise BrokerError("Množství musí být kladné.")
    bracket = broker.supports_bracket_for(plan.symbol) and not plan.reduces_position
    order = broker.submit_order(
        OrderRequest(
            symbol=plan.symbol,
            side=plan.side,
            qty=plan.qty,
            type=plan.order_type,
            limit_price=plan.limit_price,
            stop_loss=plan.stop if bracket else None,
            take_profit=plan.target if bracket else None,
        )
    )
    if journal is not None:
        journal.log_order(
            broker.name,
            plan.symbol,
            plan.side.value,
            plan.qty,
            plan.order_type.value,
            plan.entry,
            plan.stop,
            plan.target,
            strategy=source,
            reason=("exit " if plan.reduces_position else "entry ") + source,
            order_id=order.id,
            status=order.status.value,
        )
    return order
