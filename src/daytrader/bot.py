"""Automated strategy execution loop.

Each iteration: sync the broker, fetch completed bars, evaluate the strategy and act with
the same rules as the backtester (enter only on a *fresh* signal, exit when the signal
turns), under the risk manager's limits. Positions are flattened shortly before the
session closes and no new trades are opened near the close.
"""

from __future__ import annotations

import threading
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime

import numpy as np
import pandas as pd

from .analysis.indicators import atr
from .brokers.base import Broker, BrokerError
from .data.base import DataError, DataProvider, drop_incomplete_bar, to_utc, utcnow
from .journal import Journal
from .models import OrderRequest, OrderType, Position, Side
from .risk import RiskManager
from .sessions import is_crypto_symbol, session_for_symbol
from .strategies import Strategy
from .timeframes import interval_seconds, interval_timedelta


def symbol_key(symbol: str) -> str:
    return symbol.upper().replace("/", "").replace("-", "")


@dataclass
class BotConfig:
    symbols: list[str]
    interval: str = "5m"
    lookback: str = "5d"
    flatten_minutes_before_close: float = 5.0
    no_entry_minutes_before_close: float = 15.0
    stale_bars: int = 3
    poll_seconds: int | None = None
    dry_run: bool = False


@dataclass
class Decision:
    symbol: str
    action: str  # skip | hold | enter_long | enter_short | exit | flatten | blocked | error
    message: str
    warnings: list[str] = field(default_factory=list)


class TradingBot:
    def __init__(
        self,
        broker: Broker,
        provider: DataProvider,
        strategy: Strategy,
        risk: RiskManager,
        journal: Journal,
        config: BotConfig,
        clock: Callable[[], datetime] = utcnow,
    ) -> None:
        self.broker = broker
        self.provider = provider
        self.strategy = strategy
        self.risk = risk
        self.journal = journal
        self.config = config
        self.clock = clock
        self._entered_on_bar: dict[str, pd.Timestamp] = {}
        self._loss_logged_on: datetime | None = None

    # -- main loop -------------------------------------------------------------------
    def run_once(self) -> list[Decision]:
        now = self.clock()
        try:
            self.broker.sync()
        except BrokerError as exc:
            self.journal.log(f"Synchronizace brokera selhala: {exc}", "warning", "bot", ts=now)
        account = self.broker.get_account()
        positions = self.broker.get_positions()
        day_start = to_utc(now).normalize().to_pydatetime()
        trades_today = self.journal.entries_since(day_start, self.broker.name)
        if self.risk.daily_loss_hit(account) and self._loss_logged_on != day_start:
            self._loss_logged_on = day_start
            self.journal.log("Denní limit ztráty dosažen – bot dnes neotevírá nové obchody.", "warning", "bot", ts=now)

        decisions = []
        for symbol in self.config.symbols:
            by_key = {symbol_key(p.symbol): p for p in positions}
            try:
                decision = self._handle(symbol, now, account, positions, by_key.get(symbol_key(symbol)), trades_today)
            except (DataError, BrokerError, ValueError) as exc:
                decision = Decision(symbol, "error", f"Chyba: {exc}")
            if decision.action.startswith("enter"):
                trades_today += 1
            if decision.action.startswith("enter") or decision.action in ("exit", "flatten"):
                # later symbols in this cycle must see the new exposure (max positions, buying power)
                if self.config.dry_run:
                    if decision.action.startswith("enter"):
                        positions = [*positions, Position(symbol, 1 if decision.action == "enter_long" else -1, 0.0)]
                else:
                    account = self.broker.get_account()
                    positions = self.broker.get_positions()
            if decision.action not in ("hold", "skip"):
                level = {"error": "error", "blocked": "warning"}.get(decision.action, "info")
                self.journal.log(decision.message, level, "bot", symbol, ts=now)
            decisions.append(decision)
        return decisions

    def run_forever(
        self,
        stop_event: threading.Event | None = None,
        on_decisions: Callable[[list[Decision]], None] | None = None,
    ) -> None:
        stop_event = stop_event or threading.Event()
        bar_seconds = interval_seconds(self.config.interval)
        poll = self.config.poll_seconds or min(bar_seconds, 60)
        self.journal.log(
            f"Bot spuštěn: {self.strategy.label()} | {', '.join(self.config.symbols)} | "
            f"{self.config.interval} | broker {self.broker.name}{' | SUCHÝ BĚH' if self.config.dry_run else ''}",
            source="bot",
        )
        try:
            while not stop_event.is_set():
                try:
                    decisions = self.run_once()
                except Exception as exc:  # keep running through temporary API/network failures
                    self.journal.log(f"Chyba v cyklu bota: {exc}", "error", "bot")
                    decisions = [Decision("*", "error", f"Chyba v cyklu bota: {exc}")]
                if on_decisions:
                    on_decisions(decisions)
                now = time.time()
                next_run = (now // poll + 1) * poll + 3  # a few seconds after the bar closes
                stop_event.wait(max(1.0, next_run - now))
        finally:
            self.journal.log("Bot zastaven.", source="bot")

    # -- per-symbol logic ------------------------------------------------------------------
    def _handle(
        self,
        symbol: str,
        now: datetime,
        account,
        positions: list[Position],
        position: Position | None,
        trades_today: int,
    ) -> Decision:
        cfg = self.config
        session = session_for_symbol(symbol)
        if not session.is_open(now):
            return Decision(symbol, "skip", "Trh je zavřený.")
        minutes_left = session.minutes_to_close(now)
        side_now = int(np.sign(position.qty)) if position else 0

        if side_now and minutes_left is not None and minutes_left <= cfg.flatten_minutes_before_close:
            self._close(symbol, position, "eod")
            return Decision(symbol, "flatten", f"Konec seance za {minutes_left:.0f} min – pozice uzavřena.")

        bars = drop_incomplete_bar(self.provider.get_bars(symbol, cfg.interval, cfg.lookback), cfg.interval, now)
        if len(bars) < 30:
            return Decision(symbol, "skip", "Málo dat pro výpočet signálu.")
        age = to_utc(now) - bars.index[-1].tz_convert("UTC") - interval_timedelta(cfg.interval)
        if age > interval_timedelta(cfg.interval) * cfg.stale_bars:
            return Decision(symbol, "skip", "Poslední svíčka je zastaralá (svátek, přerušený feed?).")

        signals = self.strategy.generate_signals(bars)
        if not (self.risk.config.allow_short and self.broker.supports_short):
            signals = signals.clip(lower=0)
        signal, previous = int(signals.iloc[-1]), int(signals.iloc[-2])
        bar_time = bars.index[-1]
        price = float(bars["close"].iloc[-1])
        try:
            price = self.provider.get_latest_price(symbol)
        except DataError:
            pass

        if side_now and not self.broker.supports_bracket:
            hit = self._client_side_exit(symbol, side_now, price)
            if hit:
                self._close(symbol, position, hit)
                return Decision(symbol, "exit", f"{'Stop-loss' if hit == 'stop' else 'Take-profit'} zasažen @ {price:.2f}.")

        exit_message = ""
        if side_now and signal != side_now:
            self._close(symbol, position, "signal")
            side_now = 0
            exit_message = "Signál se otočil – pozice uzavřena."
            positions = [p for p in positions if symbol_key(p.symbol) != symbol_key(symbol)]
            if not cfg.dry_run:
                account = self.broker.get_account()  # buying power freed by the exit

        if side_now == 0 and signal != 0 and signal != previous:
            if self._entered_on_bar.get(symbol) == bar_time:
                decision = Decision(symbol, "hold", "Na tento signál už se vstupovalo.")
            elif minutes_left is not None and minutes_left <= cfg.no_entry_minutes_before_close:
                decision = Decision(symbol, "skip", "Blízko konce seance – nové obchody se neotevírají.")
            else:
                side = Side.BUY if signal > 0 else Side.SELL
                decision = self._enter(symbol, side, price, bars, account, positions, trades_today, bar_time)
            if exit_message:
                action = decision.action if decision.action.startswith("enter") else "exit"
                decision = Decision(symbol, action, f"{exit_message} {decision.message}", decision.warnings)
            return decision
        if exit_message:
            return Decision(symbol, "exit", exit_message)
        return Decision(symbol, "hold", f"Beze změny (signál {signal:+d}, pozice {side_now:+d}).")

    def _enter(self, symbol, side, price, bars, account, positions, trades_today, bar_time) -> Decision:
        atr_value = float(atr(bars).iloc[-1])
        stop, target = self.risk.levels(side, price, atr_value)
        fractional = self.broker.fractional or is_crypto_symbol(symbol)
        qty = self.risk.size(account.equity, price, stop, fractional=fractional)
        check = self.risk.check_new_trade(account, positions, symbol, side, qty, price, stop, trades_today)
        if not check.allowed:
            return Decision(symbol, "blocked", "Vstup zablokován: " + " ".join(check.reasons), check.warnings)
        label = "long" if side is Side.BUY else "short"
        plan = (
            f"{label} {qty:g} ks @ ~{price:.2f}"
            + (f", SL {stop:.2f}" if stop is not None else "")
            + (f", TP {target:.2f}" if target is not None else "")
        )
        if self.config.dry_run:
            self._entered_on_bar[symbol] = bar_time
            return Decision(symbol, f"enter_{label}", f"[SUCHÝ BĚH] Vstup {plan}", check.warnings)
        bracket = self.broker.supports_bracket
        order = self.broker.submit_order(
            OrderRequest(
                symbol=symbol,
                side=side,
                qty=qty,
                type=OrderType.MARKET,
                stop_loss=stop if bracket else None,
                take_profit=target if bracket else None,
                client_order_id=f"dt-{self.strategy.key}-{uuid.uuid4().hex[:10]}",
            )
        )
        self._entered_on_bar[symbol] = bar_time
        self.journal.log_order(
            self.broker.name, symbol, side.value, qty, "market", price, stop, target,
            strategy=self.strategy.label(), reason=f"entry {label}", order_id=order.id, status=order.status.value,
            ts=self.clock(),
        )
        if not bracket:
            self.journal.set_state(symbol, label, price, stop, target)
        return Decision(symbol, f"enter_{label}", f"Vstup {plan}", check.warnings)

    def _client_side_exit(self, symbol: str, side: int, price: float) -> str | None:
        state = self.journal.get_state(symbol)
        if not state:
            return None
        stop, target = state.get("stop"), state.get("target")
        if side > 0:
            if stop is not None and price <= stop:
                return "stop"
            if target is not None and price >= target:
                return "target"
        else:
            if stop is not None and price >= stop:
                return "stop"
            if target is not None and price <= target:
                return "target"
        return None

    def _close(self, symbol: str, position: Position, reason: str) -> None:
        if self.config.dry_run:
            return
        order = self.broker.close_position(position.symbol)
        self.journal.log_order(
            self.broker.name,
            symbol,
            "sell" if position.qty > 0 else "buy",
            abs(position.qty),
            "market",
            position.current_price,
            strategy=self.strategy.label(),
            reason=f"exit {reason}",
            order_id=order.id if order else None,
            status=order.status.value if order else None,
            ts=self.clock(),
        )
        self.journal.clear_state(symbol)
