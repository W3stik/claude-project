from datetime import datetime, timedelta, timezone

import pytest

from daytrader.bot import BotConfig, TradingBot
from daytrader.brokers.base import BrokerError
from daytrader.brokers.paper import PaperBroker
from daytrader.data.synthetic import SyntheticProvider
from daytrader.journal import Journal, round_trips
from daytrader.models import OrderRequest, Side
from daytrader.risk import RiskConfig, RiskManager
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
