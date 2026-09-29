from datetime import datetime, timedelta, timezone

import pytest

from daytrader.brokers.base import BrokerError
from daytrader.brokers.paper import PaperBroker, trigger_price
from daytrader.models import OrderRequest, OrderStatus, OrderType, Side

from .conftest import Clock

MONDAY_1000_NY = datetime(2026, 9, 21, 14, 0, tzinfo=timezone.utc)


@pytest.fixture
def market_clock():
    return Clock(MONDAY_1000_NY)


@pytest.fixture
def broker(tmp_path, market_clock):
    from daytrader.data.synthetic import SyntheticProvider

    provider = SyntheticProvider(now=market_clock)
    return PaperBroker(tmp_path / "paper.db", provider, starting_cash=10_000, slippage_bps=0, clock=market_clock,
                       allow_short=True)


def test_trigger_price_rules():
    assert trigger_price(OrderType.LIMIT, Side.BUY, 99, None, 100, 101, 98.5) == 99
    assert trigger_price(OrderType.LIMIT, Side.BUY, 99, None, 98, 101, 97) == 98  # gapped below the limit
    assert trigger_price(OrderType.STOP, Side.SELL, None, 95, 97, 98, 94) == 95
    assert trigger_price(OrderType.STOP, Side.SELL, None, 95, 93, 94, 92) == 93  # gapped through the stop
    assert trigger_price(OrderType.LIMIT, Side.SELL, 105, None, 100, 104, 99) is None


def test_market_buy_updates_cash_and_position(broker):
    price = broker.provider.get_latest_price("AAPL")
    order = broker.submit_order(OrderRequest("AAPL", Side.BUY, 5))
    assert order.status is OrderStatus.FILLED
    assert order.filled_avg_price == pytest.approx(price)
    position = broker.get_position("AAPL")
    assert position.qty == 5 and position.avg_price == pytest.approx(price)
    account = broker.get_account()
    assert account.cash == pytest.approx(10_000 - 5 * price)
    assert account.equity == pytest.approx(10_000)
    assert len(broker.get_fills()) == 1


def test_bracket_stop_fills_on_sync_and_cancels_target(broker, market_clock):
    from daytrader.data.synthetic import SyntheticProvider

    price = broker.provider.get_latest_price("AAPL")
    # Peek at the (deterministic) rest of the day to place a stop that is guaranteed to be touched.
    peek = SyntheticProvider(now=lambda: MONDAY_1000_NY + timedelta(hours=6))
    future = peek.get_bars("AAPL", "1m", start=MONDAY_1000_NY + timedelta(minutes=1), end=MONDAY_1000_NY + timedelta(hours=6))
    assert future["low"].min() < price
    stop = (price + future["low"].min()) / 2
    broker.submit_order(OrderRequest("AAPL", Side.BUY, 5, stop_loss=stop, take_profit=price * 1.5))
    legs = broker.get_orders("open")
    assert sorted(o.type.value for o in legs) == ["limit", "stop"]
    for _ in range(12):  # walk forward until the stop is touched
        market_clock.now += timedelta(minutes=30)
        broker.sync()
        if broker.get_position("AAPL") is None:
            break
    statuses = {o.type.value: o.status for o in broker.get_orders("all") if o.parent_id}
    assert broker.get_position("AAPL") is None
    assert statuses["stop"] is OrderStatus.FILLED
    assert statuses["limit"] is OrderStatus.CANCELED


def test_limit_order_rests_until_touched(broker, market_clock):
    price = broker.provider.get_latest_price("AAPL")
    order = broker.submit_order(OrderRequest("AAPL", Side.BUY, 1, type=OrderType.LIMIT, limit_price=price * 0.5))
    assert order.status is OrderStatus.NEW
    market_clock.now += timedelta(minutes=30)
    broker.sync()
    assert broker.get_orders("open")[0].id == order.id


def test_day_limit_order_expires_next_session(broker, market_clock):
    price = broker.provider.get_latest_price("AAPL")
    broker.submit_order(OrderRequest("AAPL", Side.BUY, 1, type=OrderType.LIMIT, limit_price=price * 0.5))
    market_clock.now += timedelta(days=1)
    broker.sync()
    assert broker.get_orders("open") == []
    assert broker.get_orders("closed")[0].status is OrderStatus.EXPIRED


def test_market_order_queued_while_closed_fills_at_open(broker, market_clock):
    market_clock.now = datetime(2026, 9, 21, 11, 0, tzinfo=timezone.utc)  # 07:00 New York
    order = broker.submit_order(OrderRequest("AAPL", Side.BUY, 2))
    assert order.status is OrderStatus.NEW
    market_clock.now = datetime(2026, 9, 21, 13, 45, tzinfo=timezone.utc)  # 09:45 New York
    broker.sync()
    fills = broker.get_fills()
    assert len(fills) == 1
    first_bar = broker.provider.get_bars("AAPL", "1m", start="2026-09-21 13:30", end="2026-09-21 13:31")
    assert fills[0].price == pytest.approx(first_bar["open"].iloc[0])


def test_rejects_orders_beyond_buying_power(broker):
    with pytest.raises(BrokerError, match="kupní síla"):
        broker.submit_order(OrderRequest("AAPL", Side.BUY, 100_000))


def test_short_disabled(tmp_path, market_clock):
    from daytrader.data.synthetic import SyntheticProvider

    broker = PaperBroker(tmp_path / "p2.db", SyntheticProvider(now=market_clock), clock=market_clock, allow_short=False)
    with pytest.raises(BrokerError, match="Shortování"):
        broker.submit_order(OrderRequest("AAPL", Side.SELL, 1))


def test_short_and_cover(broker):
    broker.submit_order(OrderRequest("MSFT", Side.SELL, 3))
    assert broker.get_position("MSFT").qty == -3
    broker.close_position("MSFT")
    assert broker.get_position("MSFT") is None
    assert broker.get_account().cash == pytest.approx(10_000)  # no slippage, same price


def test_close_position_cancels_bracket_legs(broker):
    price = broker.provider.get_latest_price("AAPL")
    broker.submit_order(OrderRequest("AAPL", Side.BUY, 2, stop_loss=price * 0.9, take_profit=price * 1.1))
    broker.close_position("AAPL")
    assert broker.get_orders("open") == []
    assert broker.get_position("AAPL") is None


def test_fractional_shares_rejected_for_stocks(broker):
    with pytest.raises(BrokerError, match="celých"):
        broker.submit_order(OrderRequest("AAPL", Side.BUY, 1.5))


def test_reset(broker):
    broker.submit_order(OrderRequest("AAPL", Side.BUY, 1))
    broker.reset(5_000)
    account = broker.get_account()
    assert account.cash == 5_000 and broker.get_positions() == [] and broker.get_fills() == []
