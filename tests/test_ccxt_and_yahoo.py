from datetime import datetime, timezone

import pandas as pd
import pytest

from daytrader.brokers.base import BrokerError
from daytrader.brokers.ccxt_broker import CCXTBroker
from daytrader.data.base import DataError
from daytrader.data.ccxt_provider import CCXTDataProvider
from daytrader.data.yahoo import YahooProvider, parse_yahoo_news
from daytrader.models import OrderRequest, OrderType, Side


class FakeExchange:
    id = "fakex"
    timeframes = {"1m": "1m", "5m": "5m", "1h": "1h"}

    def __init__(self):
        self.created = []
        start = int(pd.Timestamp("2026-09-20", tz="UTC").timestamp() * 1000)
        self.candles = [[start + i * 300_000, 100 + i, 101 + i, 99 + i, 100.5 + i, 10] for i in range(2500)]

    def fetch_ohlcv(self, symbol, timeframe="1m", since=None, limit=None):
        rows = [c for c in self.candles if since is None or c[0] >= since]
        return rows[:limit]

    def fetch_ticker(self, symbol):
        return {"last": 2000.0 if symbol == "ETH/USDT" else 100.0, "high": 110, "low": 90, "open": 95,
                "timestamp": 1_790_000_000_000}

    def load_markets(self):
        return {"ETH/USDT": {}, "BTC/USDT": {}}

    def fetch_balance(self):
        return {"total": {"USDT": 1000.0, "ETH": 0.5, "DOGE": 0.0}, "free": {"USDT": 800.0}}

    def fetch_my_trades(self, symbol, since=None, limit=None):
        return [
            {"id": "t1", "order": "o1", "symbol": symbol, "side": "buy", "amount": 1.0, "price": 1800.0, "timestamp": 1},
            {"id": "t2", "order": "o2", "symbol": symbol, "side": "sell", "amount": 0.5, "price": 1900.0, "timestamp": 2},
        ]

    def amount_to_precision(self, symbol, amount):
        return f"{amount:.4f}"

    def price_to_precision(self, symbol, price):
        return f"{price:.2f}"

    def create_order(self, symbol, type, side, amount, price=None, params=None):
        self.created.append((symbol, type, side, amount, price))
        return {"id": "x1", "symbol": symbol, "type": type, "side": side, "amount": amount, "status": "closed",
                "filled": amount, "average": 2000.0, "timestamp": 1_790_000_000_000}

    def fetch_open_orders(self, symbol=None):
        return []


def test_ccxt_provider_paginates_and_uses_utc():
    provider = CCXTDataProvider(FakeExchange())
    bars = provider.get_bars("btc-usdt", "5m", start="2026-09-20", end="2026-09-28")
    assert len(bars) == 8 * 288 + 1  # 8 days of 5-minute candles (end inclusive), fetched in pages of 1000
    assert str(bars.index.tz) == "UTC"
    assert provider.get_latest_price("ETH/USDT") == 2000.0


def test_ccxt_provider_rejects_unknown_timeframe():
    with pytest.raises(DataError):
        CCXTDataProvider(FakeExchange()).get_bars("BTC/USDT", "2h", "1d")


def test_ccxt_broker_account_positions_and_average_cost():
    broker = CCXTBroker(FakeExchange(), quote_currency="USDT", sandbox=True)
    account = broker.get_account()
    assert account.equity == pytest.approx(1000 + 0.5 * 2000)
    assert account.buying_power == 800 and not account.is_live
    (position,) = broker.get_positions()
    assert position.symbol == "ETH/USDT" and position.avg_price == pytest.approx(1800.0)


def test_ccxt_broker_orders():
    exchange = FakeExchange()
    broker = CCXTBroker(exchange, sandbox=True)
    order = broker.submit_order(OrderRequest("ETH/USDT", Side.BUY, 0.123456))
    assert exchange.created[0] == ("ETH/USDT", "market", "buy", 0.1235, None)
    assert order.filled_avg_price == 2000.0
    with pytest.raises(BrokerError, match="shortování"):
        broker.submit_order(OrderRequest("ETH/USDT", Side.SELL, 5))
    with pytest.raises(BrokerError):
        broker.submit_order(OrderRequest("ETH/USDT", Side.BUY, 1, type=OrderType.STOP, stop_price=1500))


class FakeTicker:
    def __init__(self, frame):
        self.frame = frame
        self.calls = []

    def history(self, **kwargs):
        self.calls.append(kwargs)
        return self.frame

    def get_news(self, count=10):
        return [
            {"content": {"title": "New format", "provider": {"displayName": "Reuters"},
                         "canonicalUrl": {"url": "https://example.com/a"}, "pubDate": "2026-09-21T10:00:00Z"}},
            {"title": "Old format", "publisher": "Yahoo", "link": "https://example.com/b", "providerPublishTime": 1790000000},
            {"content": {"summary": "no title"}},
        ]


def test_yahoo_normalizes_columns_and_clamps_intraday_history():
    index = pd.date_range("2026-09-21 09:30", periods=3, freq="5min", tz="America/New_York")
    frame = pd.DataFrame({"Open": [1, 2, 3], "High": [2, 3, 4], "Low": [0.5, 1, 2], "Close": [1.5, 2.5, 3.5],
                          "Volume": [10, 20, 30], "Dividends": 0, "Stock Splits": 0}, index=index)
    ticker = FakeTicker(frame)
    provider = YahooProvider(ticker_factory=lambda symbol: ticker)
    bars = provider.get_bars("AAPL", "1m", "30d")
    assert list(bars.columns) == ["open", "high", "low", "close", "volume"]
    assert provider.last_warning and "7" in provider.last_warning
    assert ticker.calls[0]["interval"] == "1m" and ticker.calls[0]["prepost"] is False


def test_yahoo_empty_frame_raises_helpful_error():
    provider = YahooProvider(ticker_factory=lambda symbol: FakeTicker(pd.DataFrame()))
    with pytest.raises(DataError, match=".PR"):
        provider.get_bars("CEZ", "5m", "5d")


def test_yahoo_news_both_formats():
    provider = YahooProvider(ticker_factory=lambda symbol: FakeTicker(pd.DataFrame()))
    news = provider.get_news("AAPL")
    assert [n.title for n in news] == ["New format", "Old format"]
    assert news[0].source == "Reuters" and news[0].url == "https://example.com/a"
    assert news[1].published == datetime.fromtimestamp(1790000000, tz=timezone.utc)
    assert parse_yahoo_news({"content": {}}) is None


def test_demo_data_keeps_working_when_the_clock_moves_on():
    from datetime import timedelta

    from daytrader.data.synthetic import SyntheticProvider

    from .conftest import Clock

    clock = Clock(datetime(2026, 9, 21, 15, 0, tzinfo=timezone.utc))  # Monday
    provider = SyntheticProvider(now=clock)
    monday = provider.get_bars("AAPL", "5m", "1d").iloc[:-1]  # the last bar is still forming
    clock.now += timedelta(days=3)  # Thursday, same process (dashboard or bot left running)
    week = provider.get_bars("AAPL", "5m", "5d")
    assert week.index[-1].date() == clock.now.date()
    assert (week.loc[monday.index, "close"] - monday["close"]).abs().max() < 1e-9  # history stays put


def test_yahoo_shares_one_download_within_a_bot_cycle():
    now = pd.Timestamp.now(tz="UTC").floor("min")
    closes = [100.0 + i for i in range(30)]
    frame = pd.DataFrame({"Open": closes, "High": closes, "Low": closes, "Close": closes, "Volume": 1.0},
                         index=pd.date_range(end=now, periods=30, freq="1min"))
    ticker = FakeTicker(frame)
    clock = {"t": 0.0}
    provider = YahooProvider(ticker_factory=lambda symbol: ticker, clock=lambda: clock["t"])
    assert len(provider.get_bars("AAPL", "1m", "5d")) == 30
    assert provider.get_latest_price("AAPL") == 129.0  # same download, no new request
    recent = provider.get_bars("AAPL", "1m", start=now - pd.Timedelta(minutes=5), end=now + pd.Timedelta(minutes=1))
    assert recent["close"].tolist() == [124.0, 125.0, 126.0, 127.0, 128.0, 129.0]
    assert len(ticker.calls) == 1
    provider.get_bars("AAPL", "1m", start=now - pd.Timedelta(hours=2), end=now - pd.Timedelta(hours=1))
    assert len(ticker.calls) == 2  # a range in the past is always downloaded
    clock["t"] += 21  # the next bot cycle downloads fresh data
    provider.get_latest_price("AAPL")
    assert len(ticker.calls) == 3 and ticker.calls[-1]["period"] == "1d"


def test_yahoo_pauses_after_too_many_requests():
    from daytrader.data.base import DataRateLimited

    calls = []

    class Limited:
        def history(self, **kwargs):
            calls.append(kwargs)
            raise RuntimeError("Too Many Requests. Rate limited. Try after a while.")

    clock = {"t": 0.0}
    provider = YahooProvider(ticker_factory=lambda symbol: Limited(), clock=lambda: clock["t"])
    with pytest.raises(DataRateLimited):
        provider.get_bars("AAPL", "1m", "1d")
    for ask in (lambda: provider.get_bars("MSFT", "1m", "1d"), lambda: provider.get_latest_price("MSFT")):
        with pytest.raises(DataRateLimited):
            ask()  # paused: Yahoo is not asked at all
    assert len(calls) == 1
    clock["t"] += 61
    with pytest.raises(DataRateLimited):
        provider.get_bars("MSFT", "1m", "1d")  # asked again after a minute, refused again …
    assert len(calls) == 2
    clock["t"] += 61
    with pytest.raises(DataRateLimited):
        provider.get_bars("MSFT", "1m", "1d")  # … so now it waits two minutes
    assert len(calls) == 2
