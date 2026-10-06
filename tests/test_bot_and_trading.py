from datetime import datetime, timedelta, timezone

import pytest

from daytrader.bot import BotConfig, TradingBot
from daytrader.brokers.base import BrokerError
from daytrader.brokers.paper import PaperBroker
from daytrader.data.synthetic import SyntheticProvider
from daytrader.journal import Journal, round_trips
from daytrader.models import OrderRequest, Side
from daytrader.risk import RiskConfig, RiskManager
from daytrader.sessions import is_crypto_symbol
from daytrader.strategies import get_strategy
from daytrader.trading import execute_plan, plan_order

from .conftest import Clock

MONDAY_0940_NY = datetime(2026, 9, 21, 13, 40, 5, tzinfo=timezone.utc)


def make_env(tmp_path, strategy="vwap_trend", dry_run=False, risk=None, symbols=("AAPL", "MSFT")):
    clock = Clock(MONDAY_0940_NY)
    provider = SyntheticProvider(now=clock)
    broker = PaperBroker(tmp_path / "paper.db", provider, clock=clock, allow_short=True)
    journal = Journal(tmp_path / "journal.db")
    bot = TradingBot(
        broker, provider, get_strategy(strategy),
        risk or RiskManager(RiskConfig(allow_short=True, max_trades_per_day=50)), journal,
        BotConfig(symbols=list(symbols), interval="5m", lookback="5d", dry_run=dry_run), clock=clock,
    )
    return clock, broker, journal, bot


def run_day(clock, bot, minutes=390):
    actions = []
    start = clock.now
    for step in range(0, minutes, 5):
        clock.now = start + timedelta(minutes=step)
        actions += bot.run_once()
    return actions


def test_bot_trades_and_flattens_before_close(tmp_path):
    clock, broker, journal, bot = make_env(tmp_path)
    actions = run_day(clock, bot)
    kinds = {a.action for a in actions}
    assert {"enter_long", "enter_short"} & kinds
    assert broker.get_positions() == []  # flattened before the close
    trips = round_trips(broker.get_fills())
    assert len(trips) > 0
    assert journal.entries_since(MONDAY_0940_NY - timedelta(hours=1), "paper") == sum(
        a.action.startswith("enter") for a in actions
    )
    # every entry carried a stop-loss (bracket legs were created)
    assert any(o.parent_id for o in broker.get_orders("all", limit=1000))


def test_dry_run_places_no_orders(tmp_path):
    clock, broker, _, bot = make_env(tmp_path, dry_run=True)
    actions = run_day(clock, bot, minutes=120)
    assert any(a.action.startswith("enter") and "SUCHÝ BĚH" in a.message for a in actions)
    assert broker.get_fills() == []


def test_bot_skips_closed_market(tmp_path):
    clock, _, _, bot = make_env(tmp_path)
    clock.now = datetime(2026, 9, 26, 15, 0, tzinfo=timezone.utc)  # Saturday
    assert {a.action for a in bot.run_once()} == {"skip"}


def test_bot_respects_max_open_positions(tmp_path):
    risk = RiskManager(RiskConfig(allow_short=True, max_open_positions=1, max_trades_per_day=50))
    clock, broker, _, bot = make_env(tmp_path, risk=risk, symbols=("AAPL", "MSFT", "NVDA", "AMD"))
    for _ in range(40):
        clock.now += timedelta(minutes=5)
        bot.run_once()
        assert len(broker.get_positions()) <= 1


def test_plan_order_sizes_from_risk_and_executes(tmp_path):
    clock, broker, journal, _ = make_env(tmp_path)
    risk = RiskManager(RiskConfig(max_position_pct=100))
    plan = plan_order(broker, broker.provider, risk, "AAPL", Side.BUY, journal=journal)
    assert plan.stop is not None and plan.stop < plan.entry < plan.target
    assert plan.qty == risk.size(plan.equity, plan.entry, plan.stop) > 0
    assert plan.risk_pct <= 1.0 + 1e-9
    assert plan.reward_risk == pytest.approx(2.0, rel=0.01)
    order = execute_plan(broker, plan, journal)
    assert order.filled_qty == plan.qty
    assert len(broker.get_orders("open")) == 2  # stop-loss and take-profit legs


def test_plan_order_for_exit_skips_new_trade_checks(tmp_path):
    clock, broker, journal, _ = make_env(tmp_path)
    broker.submit_order(OrderRequest("AAPL", Side.BUY, 3))
    plan = plan_order(broker, broker.provider, RiskManager(), "AAPL", Side.SELL, journal=journal)
    assert plan.reduces_position and plan.qty == 3 and plan.check.allowed
    execute_plan(broker, plan, journal)
    assert broker.get_position("AAPL") is None


def test_execute_plan_refuses_blocked_plan(tmp_path):
    clock, broker, journal, _ = make_env(tmp_path)
    plan = plan_order(broker, broker.provider, RiskManager(RiskConfig(allow_short=False)), "AAPL", Side.SELL)
    assert not plan.check.allowed
    with pytest.raises(BrokerError):
        execute_plan(broker, plan, journal)


class CountingProvider(SyntheticProvider):
    def __init__(self, now):
        super().__init__(now=now)
        self.bar_calls = 0

    def get_bars(self, symbol, interval="5m", period="5d", start=None, end=None):
        if interval == "5m":
            self.bar_calls += 1
        return super().get_bars(symbol, interval, period, start, end)


def test_bot_downloads_bars_only_when_a_new_bar_is_due(tmp_path):
    clock = Clock(MONDAY_0940_NY)
    provider = CountingProvider(clock)
    broker = PaperBroker(tmp_path / "paper.db", provider, clock=clock)
    bot = TradingBot(broker, provider, get_strategy("ema_cross"), RiskManager(), Journal(tmp_path / "j.db"),
                     BotConfig(symbols=["AAPL"], interval="5m"), clock=clock)
    bot.run_once()
    assert provider.bar_calls == 1
    clock.now += timedelta(minutes=1)  # same bar still forming
    decisions = bot.run_once()
    assert provider.bar_calls == 1 and decisions[0].message == "Čekám na další svíčku."
    clock.now += timedelta(minutes=5)  # a new 5-minute bar has closed
    bot.run_once()
    assert provider.bar_calls == 2
    assert bot.last_run == clock.now


def test_only_one_bot_per_account(tmp_path):
    import threading

    from daytrader.bot import BotAlreadyRunning

    clock, broker, journal, bot = make_env(tmp_path)
    now = datetime.now(timezone.utc)
    assert journal.acquire_bot_lock(broker.account_key, "other", "bot z bot.bat", now) is None
    assert journal.bot_lock_holder(broker.account_key, now) == "bot z bot.bat"
    stop = threading.Event()
    stop.set()
    with pytest.raises(BotAlreadyRunning):
        bot.run_forever(stop)
    # a lock without heartbeat for a while (crashed bot) is taken over
    later = now + timedelta(minutes=10)
    assert journal.bot_lock_holder(broker.account_key, later) is None
    assert journal.acquire_bot_lock(broker.account_key, "mine", "nový bot", later) is None
    journal.release_bot_lock(broker.account_key, "mine")
    assert journal.bot_lock_holder(broker.account_key, later) is None


def test_run_forever_releases_lock(tmp_path):
    import threading

    clock, broker, journal, bot = make_env(tmp_path)
    stop = threading.Event()
    stop.set()
    bot.run_forever(stop)
    assert journal.bot_lock_holder(broker.account_key, datetime.now(timezone.utc)) is None


def test_paper_price_cache_follows_broker_clock(tmp_path):
    clock = Clock(MONDAY_0940_NY)

    class Prices(SyntheticProvider):
        calls = 0

        def get_latest_price(self, symbol):
            Prices.calls += 1
            return super().get_latest_price(symbol)

    broker = PaperBroker(tmp_path / "p.db", Prices(now=clock), clock=clock)
    broker.get_account()
    broker.submit_order(OrderRequest("AAPL", Side.BUY, 1))
    broker.get_positions()
    broker.get_positions()
    assert Prices.calls == 1
    clock.now += timedelta(minutes=1)
    broker.get_positions()
    assert Prices.calls == 2


class AlpacaLikeCrypto(PaperBroker):
    """Like Alpaca: crypto orders cannot carry stop-loss/take-profit legs and cannot go short."""

    def supports_bracket_for(self, symbol):
        return not is_crypto_symbol(symbol)

    def supports_short_for(self, symbol):
        return not is_crypto_symbol(symbol)

    def submit_order(self, request):
        if is_crypto_symbol(request.symbol) and (request.stop_loss or request.take_profit):
            raise BrokerError("Alpaca nepodporuje bracket příkazy pro krypto.")
        return super().submit_order(request)


def test_bot_trades_crypto_where_the_broker_has_no_brackets(tmp_path):
    clock = Clock(MONDAY_0940_NY)
    provider = SyntheticProvider(now=clock)
    broker = AlpacaLikeCrypto(tmp_path / "paper.db", provider, clock=clock, allow_short=True)
    journal = Journal(tmp_path / "journal.db")
    bot = TradingBot(
        broker, provider, get_strategy("ema_cross"),
        RiskManager(RiskConfig(allow_short=True, max_trades_per_day=50)), journal,
        BotConfig(symbols=["BTC/USD", "AAPL"], interval="5m"), clock=clock,
    )
    entered = None
    for _ in range(200):
        clock.now += timedelta(minutes=5)
        decisions = {d.symbol: d for d in bot.run_once()}
        assert decisions["BTC/USD"].action != "error", decisions["BTC/USD"].message
        if decisions["BTC/USD"].action.startswith("enter"):
            entered = decisions["BTC/USD"]
            break
    assert entered is not None and entered.action == "enter_long"  # long only: no crypto shorts
    assert not any(o.parent_id and o.symbol == "BTC/USD" for o in broker.get_orders("all", limit=1000))
    state = journal.get_state("BTC/USD")
    assert state["stop"] is not None and state["target"] is not None  # watched by the bot itself
    # the bot closes the position itself once the price crosses the stop
    journal.set_state("BTC/USD", "long", state["entry"], provider.get_latest_price("BTC/USD") * 1.5, None)
    clock.now += timedelta(minutes=1)
    decision = next(d for d in bot.run_once() if d.symbol == "BTC/USD")
    assert decision.action == "exit" and "Stop-loss" in decision.message
    assert broker.get_position("BTC/USD") is None


MONDAY_0900_PRAGUE = datetime(2026, 9, 21, 7, 0, 5, tzinfo=timezone.utc)


def delayed_bot(tmp_path, delay):
    """Bot on a feed that trails the clock like Yahoo's Prague data (20 minutes)."""
    clock = Clock(MONDAY_0900_PRAGUE)
    provider = SyntheticProvider(now=lambda: clock.now - delay)
    broker = PaperBroker(tmp_path / "paper.db", provider, clock=clock)
    strategy = get_strategy("ema_cross")
    seen = []
    original = strategy.generate_signals

    def recording(bars):
        seen.append((clock.now, bars.index[-1]))
        return original(bars)

    strategy.generate_signals = recording
    bot = TradingBot(broker, provider, strategy, RiskManager(RiskConfig(max_trades_per_day=50)),
                     Journal(tmp_path / "journal.db"), BotConfig(symbols=["CEZ.PR"], interval="5m"), clock=clock)
    return clock, broker, bot, seen


def test_bot_trades_on_a_delayed_feed(tmp_path):
    delay = timedelta(minutes=20)
    clock, broker, bot, seen = delayed_bot(tmp_path, delay)
    actions, stale = [], []
    for _ in range(7 * 60 + 20):  # 9:00-16:20 Prague, polled every minute
        for decision in bot.run_once():
            actions.append(decision)
            if "zastaralá" in decision.message:
                stale.append(clock.now)
        clock.now += timedelta(minutes=1)
    assert any(a.action.startswith("enter") for a in actions)
    # stale only until the first bar of the day has closed at the source (9:05 + 20 min)
    assert stale and max(stale) < MONDAY_0900_PRAGUE + timedelta(minutes=25)
    # only bars that are complete at the source are evaluated, never the one still forming,
    # and never yesterday's last bar
    assert seen and all(last + timedelta(minutes=5) <= now - delay for now, last in seen)
    assert all(last >= MONDAY_0900_PRAGUE.replace(second=0) for _, last in seen)
    assert len({last for _, last in seen}) == len(seen)  # each bar once, although polled every minute
    assert broker.get_positions() == []  # flattened before the 16:20 close


def test_bot_still_skips_a_feed_that_stopped(tmp_path):
    clock, _, bot, _ = delayed_bot(tmp_path, timedelta(hours=3))  # e.g. a holiday: last bars are old
    clock.now += timedelta(hours=3)
    decision = bot.run_once()[0]
    assert decision.action == "skip" and "zastaralá" in decision.message


def test_bot_never_goes_back_to_an_older_bar_on_a_quiet_feed(tmp_path):
    from daytrader.timeframes import interval_timedelta

    clock = Clock(MONDAY_0940_NY)
    quiet_bar = datetime(2026, 9, 21, 13, 45, tzinfo=timezone.utc)  # 9:45 NY: no trades at all

    class Quiet(SyntheticProvider):
        """Only bars with trades exist, and a new bar appears only with its first trade."""

        def get_bars(self, symbol, interval="5m", period="5d", start=None, end=None):
            bars = super().get_bars(symbol, interval, period, start, end)
            complete = bars.index + interval_timedelta(interval) <= clock.now
            return bars[complete & (bars.index != quiet_bar)]

    provider = Quiet(now=clock)
    strategy = get_strategy("ema_cross")
    seen = []
    original = strategy.generate_signals

    def recording(bars):
        seen.append(bars.index[-1])
        return original(bars)

    strategy.generate_signals = recording
    bot = TradingBot(PaperBroker(tmp_path / "paper.db", provider, clock=clock), provider, strategy, RiskManager(),
                     Journal(tmp_path / "journal.db"), BotConfig(symbols=["AAPL"], interval="5m"), clock=clock)
    for _ in range(30):
        bot.run_once()
        clock.now += timedelta(minutes=1)
    assert len(seen) > 3 and seen == sorted(set(seen))


def test_minute_bot_scalps_with_short_holds(tmp_path):
    import pandas as pd

    clock = Clock(datetime(2026, 9, 21, 13, 30, 3, tzinfo=timezone.utc))  # Monday 9:30 New York
    provider = SyntheticProvider(now=clock)
    broker = PaperBroker(tmp_path / "paper.db", provider, clock=clock)
    bot = TradingBot(broker, provider, get_strategy("scalp"), RiskManager(RiskConfig(max_trades_per_day=100)),
                     Journal(tmp_path / "journal.db"), BotConfig(symbols=["AAPL", "NVDA", "SPY"], interval="1m"),
                     clock=clock)
    actions = []
    for _ in range(180):  # checks the market every minute
        actions += bot.run_once()
        clock.now += timedelta(minutes=1)
    assert not [a.message for a in actions if a.action == "error"]
    trips = round_trips(broker.get_fills())
    assert len(trips) >= 5
    minutes = (pd.to_datetime(trips["exit_time"]) - pd.to_datetime(trips["entry_time"])).dt.total_seconds() / 60
    assert minutes.max() <= 11  # max_hold = 10 bars


class CountingSynthetic(SyntheticProvider):
    def __init__(self, now, parallel=1, broken=()):
        super().__init__(now=now)
        self.parallel_requests = parallel
        self.requests = []
        self.broken = set(broken)

    def get_bars(self, symbol, interval="5m", period="5d", start=None, end=None):
        if symbol in self.broken:
            from daytrader.data.base import DataError

            raise DataError(f"{symbol}: nic")
        if interval == "1m" and end is None:
            self.requests.append((symbol, "full" if start is None else "new"))
        return super().get_bars(symbol, interval, period, start, end)

    def get_latest_price(self, symbol):  # not one of the bot's bar downloads
        return float(SyntheticProvider.get_bars(self, symbol, "1m", "7d")["close"].iloc[-1])


def minute_bot(tmp_path, provider, clock, symbols):
    broker = PaperBroker(tmp_path / "paper.db", provider, clock=clock, allow_short=True)
    risk = RiskManager(RiskConfig(allow_short=True, max_trades_per_day=1000).with_max_positions(5))
    return TradingBot(broker, provider, get_strategy("scalp", rsi=2, dip=45, take=55, max_hold=3), risk,
                      Journal(tmp_path / "journal.db"), BotConfig(symbols=symbols, interval="1m"), clock=clock)


def test_minute_bot_downloads_in_parallel_and_only_new_bars(tmp_path):
    symbols = ["AAPL", "MSFT", "NVDA", "BTC-USD", "SPY", "QQQ"]
    runs = []
    for parallel in (1, 4):
        clock = Clock(datetime(2026, 9, 21, 13, 30, 3, tzinfo=timezone.utc))
        provider = CountingSynthetic(clock, parallel=parallel)
        bot = minute_bot(tmp_path / f"p{parallel}", provider, clock, symbols)
        decisions = []
        for _ in range(90):
            decisions += [(d.symbol, d.action, d.message) for d in bot.run_once()]
            clock.now += timedelta(minutes=1)
        runs.append(decisions)
        kinds = [kind for _, kind in provider.requests]
        assert kinds.count("full") == len(symbols)  # the history is downloaded once …
        assert kinds.count("new") >= 80 * len(symbols)  # … then only the newest bars, every minute
    assert runs[0] == runs[1]  # parallel downloads change nothing about the decisions
    assert any(action.startswith("enter") for _, action, _ in runs[0])


def test_symbol_with_failing_data_is_left_out_for_a_while(tmp_path):
    clock = Clock(datetime(2026, 9, 21, 13, 30, 3, tzinfo=timezone.utc))
    provider = CountingSynthetic(clock, broken={"NOPE"})
    bot = minute_bot(tmp_path, provider, clock, ["AAPL", "NOPE"])
    messages = []
    for _ in range(5):
        decision = next(d for d in bot.run_once() if d.symbol == "NOPE")
        messages.append((decision.action, decision.message))
        clock.now += timedelta(minutes=1)
    assert [a for a, _ in messages] == ["error", "error", "error", "skip", "skip"]
    assert "vynechám" in messages[2][1] and "vynechán" in messages[3][1]
    clock.now += timedelta(minutes=30)  # tried again later
    assert next(d for d in bot.run_once() if d.symbol == "NOPE").action == "error"


def test_rate_limited_source_pauses_quietly(tmp_path):
    from daytrader.data.base import DataRateLimited

    clock = Clock(datetime(2026, 9, 21, 13, 30, 3, tzinfo=timezone.utc))

    class Limited(SyntheticProvider):
        def get_bars(self, symbol, interval="5m", period="5d", start=None, end=None):
            raise DataRateLimited("Yahoo dočasně omezilo počet dotazů.")

    provider = Limited(now=clock)
    bot = minute_bot(tmp_path, provider, clock, ["AAPL", "MSFT"])
    journal = bot.journal
    for _ in range(3):
        assert {d.action for d in bot.run_once()} == {"skip"}  # not one error per symbol and minute
        clock.now += timedelta(minutes=1)
    warnings = [m for m in journal.events(50)["message"] if "omezil" in m]
    assert len(warnings) == 1
