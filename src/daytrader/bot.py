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
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime, timezone

import numpy as np
import pandas as pd

from .analysis.indicators import atr
from .brokers.base import Broker, BrokerError
from .data.base import DataError, DataProvider, DataRateLimited, drop_incomplete_bar, to_utc, utcnow
from .journal import Journal
from .models import OrderRequest, OrderType, Position, Side
from .risk import RiskManager
from .sessions import is_crypto_symbol, session_for_symbol
from .strategies import Strategy
from .timeframes import interval_seconds, interval_timedelta

# A feed that trails the clock by more than this is treated as delayed (Yahoo publishes
# Prague and other European exchanges 15-20 minutes late).
FEED_LAG_TOLERANCE = pd.Timedelta(minutes=1)
# After the first full download only the newest bars are fetched; the last few are fetched
# again because the newest one may still have been forming. Now and then everything is
# downloaded again (splits, corrected data).
OVERLAP_BARS = 3
FULL_REFRESH = pd.Timedelta(hours=2)
# A symbol whose data keeps failing is left out for a while instead of erroring every minute.
MAX_DATA_ERRORS = 3
PARK_FOR = pd.Timedelta(minutes=30)


class BotAlreadyRunning(RuntimeError):
    """Another bot instance is already trading the same account."""


def symbol_key(symbol: str) -> str:
    return symbol.upper().replace("/", "").replace("-", "")


def symbols_label(symbols: list[str], limit: int = 8) -> str:
    shown = ", ".join(symbols[:limit])
    return shown if len(symbols) <= limit else f"{shown} … (celkem {len(symbols)})"


def next_market_open(symbols: list[str], now: datetime) -> datetime | None:
    """Earliest upcoming session open among the symbols; ``None`` if any of them trades now."""
    opens = []
    for symbol in symbols:
        session = session_for_symbol(symbol)
        if session.is_24h or session.is_open(now):
            return None
        upcoming = session.next_open(now)
        if upcoming is not None:
            opens.append(upcoming)
    return min(opens) if opens else None


@dataclass
class BotConfig:
    symbols: list[str]
    interval: str = "5m"
    lookback: str = "5d"
    flatten_minutes_before_close: float = 5.0
    no_entry_minutes_before_close: float = 15.0
    stale_bars: int = 3
    max_feed_delay_minutes: float = 30.0
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
        self._next_eval: dict[str, pd.Timestamp] = {}
        self._evaluated_bar: dict[str, pd.Timestamp] = {}
        self._history: dict[str, pd.DataFrame] = {}
        self._downloaded_at: dict[str, pd.Timestamp] = {}
        self._errors: dict[str, int] = {}
        self._parked_until: dict[str, pd.Timestamp] = {}
        self._loss_logged_on: datetime | None = None
        self._rate_limit_logged = False
        self.last_run: datetime | None = None

    # -- main loop -------------------------------------------------------------------
    def run_once(self) -> list[Decision]:
        now = self.clock()
        prefetched = self._prefetch(now)  # before the broker sync, which can then reuse the download
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
        rate_limited = False
        for symbol in self.config.symbols:
            by_key = {symbol_key(p.symbol): p for p in positions}
            try:
                decision = self._handle(
                    symbol, now, account, positions, by_key.get(symbol_key(symbol)), trades_today, prefetched
                )
            except DataRateLimited as exc:
                rate_limited = True
                decision = Decision(symbol, "skip", str(exc))
            except (DataError, BrokerError, ValueError) as exc:
                decision = Decision(symbol, "error", f"Chyba: {exc}")
                if isinstance(exc, DataError):
                    decision = self._count_data_error(symbol, now, decision)
            else:
                self._errors.pop(symbol, None)
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
        if rate_limited and not self._rate_limit_logged:
            self.journal.log("Zdroj dat dočasně omezil počet dotazů – bot chvíli počká.", "warning", "bot", ts=now)
        self._rate_limit_logged = rate_limited
        self.last_run = now
        return decisions

    # -- market data -----------------------------------------------------------------------
    def _needs_bars(self, symbol: str, now: datetime) -> bool:
        parked = self._parked_until.get(symbol)
        if parked is not None and to_utc(now) < parked:
            return False
        if not session_for_symbol(symbol).is_open(now):
            return False
        due = self._next_eval.get(symbol)
        return due is None or to_utc(now) >= due

    def _prefetch(self, now: datetime) -> dict[str, pd.DataFrame | Exception]:
        """Download bars for every symbol that needs them this cycle, several at once if the source allows."""
        due = [symbol for symbol in self.config.symbols if self._needs_bars(symbol, now)]

        def fetch(symbol: str) -> tuple[str, pd.DataFrame | Exception]:
            try:
                return symbol, self._fetch_bars(symbol, now)
            except Exception as exc:  # raised again when the symbol is handled
                return symbol, exc

        workers = min(len(due), max(1, getattr(self.provider, "parallel_requests", 1)))
        if workers <= 1:
            return dict(map(fetch, due))
        with ThreadPoolExecutor(workers, thread_name_prefix="bot-data") as pool:
            return dict(pool.map(fetch, due))

    def _fetch_bars(self, symbol: str, now: datetime) -> pd.DataFrame:
        """The lookback window of bars; after the first download only the newest bars are fetched."""
        cfg = self.config
        now_ts = to_utc(now)
        cached = self._history.get(symbol)
        downloaded = self._downloaded_at.get(symbol)
        if cached is None or cached.empty or downloaded is None or now_ts - downloaded > FULL_REFRESH:
            bars = self.provider.get_bars(symbol, cfg.interval, cfg.lookback)
            self._downloaded_at[symbol] = now_ts
        else:
            start = cached.index[-1] - OVERLAP_BARS * interval_timedelta(cfg.interval)
            fresh = self.provider.get_bars(symbol, cfg.interval, start=start)
            bars = pd.concat([cached[cached.index < fresh.index[0]], fresh]) if len(fresh) else cached
        self._history[symbol] = bars
        return bars

    def _bars(self, symbol: str, now: datetime, prefetched: dict | None) -> pd.DataFrame:
        if prefetched is not None and symbol in prefetched:
            result = prefetched[symbol]
            if isinstance(result, Exception):
                raise result
            return result
        return self._fetch_bars(symbol, now)

    def _count_data_error(self, symbol: str, now: datetime, decision: Decision) -> Decision:
        errors = self._errors.get(symbol, 0) + 1
        if errors < MAX_DATA_ERRORS:
            self._errors[symbol] = errors
            return decision
        self._errors.pop(symbol, None)
        self._parked_until[symbol] = to_utc(now) + PARK_FOR
        minutes = int(PARK_FOR.total_seconds() // 60)
        return Decision(symbol, "error", f"{decision.message} – data opakovaně selhávají, symbol na {minutes} minut vynechám.")

    def run_forever(
        self,
        stop_event: threading.Event | None = None,
        on_decisions: Callable[[list[Decision]], None] | None = None,
    ) -> None:
        stop_event = stop_event or threading.Event()
        bar_seconds = interval_seconds(self.config.interval)
        poll = self.config.poll_seconds or min(bar_seconds, 60)
        account_key = self.broker.account_key
        instance = uuid.uuid4().hex
        info = f"{self.strategy.label()} | {symbols_label(self.config.symbols)} | {self.config.interval}"
        holder = self.journal.acquire_bot_lock(account_key, instance, info, datetime.now(timezone.utc))
        if holder is not None:
            raise BotAlreadyRunning(
                f"Na tomto účtu už běží jiný bot ({holder}). Zastav ho, nebo počkej pár minut, "
                "pokud byl ukončen nečekaně."
            )
        self.journal.log(
            f"Bot spuštěn: {info} | broker {self.broker.name}{' | SUCHÝ BĚH' if self.config.dry_run else ''}",
            source="bot",
        )
        try:
            while not stop_event.is_set():
                self.journal.heartbeat_bot_lock(account_key, instance, datetime.now(timezone.utc))
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
            self.journal.release_bot_lock(account_key, instance)
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
        prefetched: dict | None = None,
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

        parked = self._parked_until.get(symbol)
        if parked is not None and to_utc(now) < parked:
            return Decision(symbol, "skip", "Dočasně vynechán – data opakovaně selhávala.")
        step = interval_timedelta(cfg.interval)
        due = self._next_eval.get(symbol)
        if due is not None and to_utc(now) < due:
            # No new bar yet: skip the data download, only watch client-side stops.
            return self._watch_stops(symbol, side_now, position) or Decision(symbol, "hold", "Čekám na další svíčku.")

        bars = self._bars(symbol, now, prefetched)
        # On a delayed feed the newest bar is still forming at the source even though, by the
        # clock, it should have closed already.
        delayed = len(bars) > 0 and to_utc(now) - bars.index[-1].tz_convert("UTC") - step > FEED_LAG_TOLERANCE
        bars = drop_incomplete_bar(bars, cfg.interval, now)
        if delayed:
            bars = bars.iloc[:-1]
        if len(bars) < 30:
            self._next_eval[symbol] = to_utc(now) + step
            return Decision(symbol, "skip", "Málo dat pro výpočet signálu.")
        last_bar = bars.index[-1].tz_convert("UTC")
        stale_after = max(step * cfg.stale_bars, pd.Timedelta(minutes=cfg.max_feed_delay_minutes))
        if to_utc(now) - last_bar - step > stale_after:
            self._next_eval[symbol] = to_utc(now) + step
            return Decision(symbol, "skip", "Poslední svíčka je zastaralá (svátek, přerušený feed?).")
        # The next bar completes at last_bar + 2 * step; no point downloading data before that.
        # A delayed feed publishes it at an unknown moment within the next step: check every poll.
        self._next_eval[symbol] = to_utc(now) if delayed else last_bar + 2 * step
        evaluated = self._evaluated_bar.get(symbol)
        if evaluated is not None and last_bar <= evaluated:  # each bar once, never an older one
            return self._watch_stops(symbol, side_now, position) or Decision(symbol, "hold", "Čekám na další svíčku.")
        self._evaluated_bar[symbol] = last_bar

        signals = self.strategy.generate_signals(bars)
        if not (self.risk.config.allow_short and self.broker.supports_short_for(symbol)):
            signals = signals.clip(lower=0)
        signal, previous = int(signals.iloc[-1]), int(signals.iloc[-2])
        bar_time = bars.index[-1]
        price = float(bars["close"].iloc[-1])
        try:
            price = self.provider.get_latest_price(symbol)
        except DataError:
            pass

        if side_now and not self.broker.supports_bracket_for(symbol):
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
        bracket = self.broker.supports_bracket_for(symbol)
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

    def _watch_stops(self, symbol: str, side: int, position: Position | None) -> Decision | None:
        """Between bars: exit at the stop-loss/take-profit the bot watches itself (no bracket orders)."""
        if not side or self.broker.supports_bracket_for(symbol):
            return None
        try:
            price = self.provider.get_latest_price(symbol)
        except DataError:
            return None
        hit = self._client_side_exit(symbol, side, price)
        if not hit:
            return None
        self._close(symbol, position, hit)
        return Decision(symbol, "exit", f"{'Stop-loss' if hit == 'stop' else 'Take-profit'} zasažen @ {price:.2f}.")

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
