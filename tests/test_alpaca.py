import json

import httpx
import pytest

from daytrader.brokers.alpaca import AlpacaBroker, decimal_str, round_price
from daytrader.brokers.base import BrokerError
from daytrader.data.alpaca import AlpacaDataProvider
from daytrader.data.base import DataError
from daytrader.models import OrderRequest, OrderStatus, Side


class FakeAlpaca:
    def __init__(self):
        self.requests: list[httpx.Request] = []
        self.routes = {}

    def route(self, method, path, response, status=200):
        self.routes[(method, path)] = (status, response)

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        key = (request.method, request.url.path)
        if key not in self.routes:
            return httpx.Response(404, json={"message": f"no route {key}"})
        status, response = self.routes[key]
        body = response(request) if callable(response) else response
        return httpx.Response(status, json=body)

    def client(self) -> httpx.Client:
        return httpx.Client(transport=httpx.MockTransport(self.handler))


ORDER = {
    "id": "o-1", "client_order_id": "c-1", "symbol": "AAPL", "qty": "10", "filled_qty": "0", "side": "buy",
    "type": "market", "time_in_force": "day", "status": "accepted", "created_at": "2026-09-21T14:00:00Z",
}


def test_account_and_positions():
    fake = FakeAlpaca()
    fake.route("GET", "/v2/account", {"equity": "10500.5", "cash": "3000", "buying_power": "20000",
                                      "last_equity": "10000", "pattern_day_trader": False, "daytrade_count": 2})
    fake.route("GET", "/v2/positions", [
        {"symbol": "AAPL", "qty": "10", "side": "long", "avg_entry_price": "150", "current_price": "155"},
        {"symbol": "TSLA", "qty": "-5", "side": "short", "avg_entry_price": "200", "current_price": "190"},
    ])
    broker = AlpacaBroker("key", "secret", paper=True, client=fake.client())
    account = broker.get_account()
    assert account.equity == 10500.5 and account.day_pnl == pytest.approx(500.5)
    assert account.day_trade_count == 2 and not account.is_live
    positions = {p.symbol: p for p in broker.get_positions()}
    assert positions["TSLA"].qty == -5
    assert positions["TSLA"].unrealized_pnl == pytest.approx(50)
    assert fake.requests[0].headers["APCA-API-KEY-ID"] == "key"
    assert str(fake.requests[0].url).startswith("https://paper-api.alpaca.markets")


def test_bracket_order_payload():
    fake = FakeAlpaca()
    fake.route("POST", "/v2/orders", lambda req: {**ORDER, **json.loads(req.content)})
    broker = AlpacaBroker("key", "secret", client=fake.client())
    order = broker.submit_order(OrderRequest("aapl", Side.BUY, 10, stop_loss=148.123, take_profit=155.987))
    body = json.loads(fake.requests[0].content)
    assert body["symbol"] == "AAPL" and body["qty"] == "10"
    assert body["order_class"] == "bracket"
    assert body["stop_loss"] == {"stop_price": "148.12"}
    assert body["take_profit"] == {"limit_price": "155.99"}
    assert order.status is OrderStatus.NEW


def test_stop_only_uses_oto_and_price_rounding():
    broker = AlpacaBroker("k", "s", client=FakeAlpaca().client())
    payload = broker.build_order_payload(OrderRequest("F", Side.BUY, 1000, stop_loss=0.51234))
    assert payload["order_class"] == "oto"
    assert payload["stop_loss"] == {"stop_price": "0.5123"}
    assert round_price(12.3456) == 12.35
    assert decimal_str(1234567.0) == "1234567" and decimal_str(0.00012) == "0.00012"


def test_crypto_bracket_rejected():
    broker = AlpacaBroker("k", "s", client=FakeAlpaca().client())
    with pytest.raises(BrokerError):
        broker.submit_order(OrderRequest("BTC/USD", Side.BUY, 0.01, stop_loss=50_000))
    # callers (bot, manual orders) ask per symbol and keep crypto stops client-side
    assert broker.supports_bracket_for("AAPL") and broker.supports_short_for("AAPL")
    assert not broker.supports_bracket_for("BTC/USD") and not broker.supports_short_for("ETH-USD")


def test_manual_crypto_order_goes_without_legs(tmp_path):
    from daytrader.data.synthetic import SyntheticProvider
    from daytrader.risk import RiskManager
    from daytrader.trading import execute_plan, plan_order

    from .conftest import FRIDAY_AFTER_CLOSE, Clock

    fake = FakeAlpaca()
    fake.route("GET", "/v2/account", {"equity": "10000", "cash": "10000", "buying_power": "10000"})
    fake.route("GET", "/v2/positions", [])
    fake.route("POST", "/v2/orders", lambda req: {**ORDER, **json.loads(req.content)})
    broker = AlpacaBroker("k", "s", client=fake.client())
    plan = plan_order(broker, SyntheticProvider(now=Clock(FRIDAY_AFTER_CLOSE)), RiskManager(), "BTC/USD", Side.BUY)
    assert plan.stop is not None and any("nepodporuje bracket" in note for note in plan.notes)
    execute_plan(broker, plan)
    body = json.loads(fake.requests[-1].content)
    assert body["symbol"] == "BTC/USD" and body["time_in_force"] == "gtc"
    assert "order_class" not in body and "stop_loss" not in body


def test_error_message_contains_hint():
    fake = FakeAlpaca()
    fake.route("GET", "/v2/account", {"message": "invalid api key"}, status=403)
    broker = AlpacaBroker("k", "s", client=fake.client())
    with pytest.raises(BrokerError, match="ALPACA_API_KEY"):
        broker.get_account()


def test_close_position_cancels_legs_first():
    fake = FakeAlpaca()
    fake.route("GET", "/v2/positions", [{"symbol": "AAPL", "qty": "10", "side": "long", "avg_entry_price": "150"}])
    fake.route("GET", "/v2/orders", [{**ORDER, "id": "parent", "status": "filled", "legs": [
        {**ORDER, "id": "leg-stop", "side": "sell", "type": "stop", "status": "held"},
        {**ORDER, "id": "leg-tp", "side": "sell", "type": "limit", "status": "new"},
    ]}])
    fake.route("DELETE", "/v2/orders/leg-stop", None)
    fake.route("DELETE", "/v2/orders/leg-tp", {"message": "order already canceled"}, status=422)
    fake.route("DELETE", "/v2/positions/AAPL", {**ORDER, "id": "close", "side": "sell"})
    broker = AlpacaBroker("k", "s", client=fake.client())
    order = broker.close_position("AAPL")
    calls = [(r.method, r.url.path) for r in fake.requests]
    assert calls.index(("DELETE", "/v2/orders/leg-stop")) < calls.index(("DELETE", "/v2/positions/AAPL"))
    assert order.id == "close"


def test_fills_map_sell_short_to_sell():
    fake = FakeAlpaca()
    fake.route("GET", "/v2/account/activities/FILL", [
        {"id": "a1", "symbol": "TSLA", "side": "sell_short", "qty": "5", "price": "200", "order_id": "o",
         "transaction_time": "2026-09-21T14:00:00Z"},
    ])
    broker = AlpacaBroker("k", "s", client=fake.client())
    fills = broker.get_fills()
    assert fills[0].side is Side.SELL and fills[0].qty == 5


def test_data_bars_pagination_timezone_and_regular_hours():
    fake = FakeAlpaca()
    pages = {
        None: {"bars": [
            {"t": "2026-09-21T13:00:00Z", "o": 1, "h": 1, "l": 1, "c": 1, "v": 10},  # 09:00 NY pre-market
            {"t": "2026-09-21T13:30:00Z", "o": 2, "h": 3, "l": 1, "c": 2.5, "v": 100},
        ], "next_page_token": "p2"},
        "p2": {"bars": [{"t": "2026-09-21T13:35:00Z", "o": 2.5, "h": 4, "l": 2, "c": 3, "v": 200}],
               "next_page_token": None},
    }
    fake.route("GET", "/v2/stocks/AAPL/bars", lambda req: pages[req.url.params.get("page_token")])
    provider = AlpacaDataProvider("k", "s", client=fake.client())
    bars = provider.get_bars("AAPL", "5m", "5d")
    assert len(bars) == 2
    assert str(bars.index.tz) == "America/New_York"
    assert bars.index[0].hour == 9 and bars.index[0].minute == 30
    params = fake.requests[0].url.params
    assert params["timeframe"] == "5Min" and params["feed"] == "iex"


def test_data_crypto_bars_and_latest_price():
    fake = FakeAlpaca()
    fake.route("GET", "/v1beta3/crypto/us/bars", {"bars": {"BTC/USD": [
        {"t": "2026-09-21T00:00:00Z", "o": 1, "h": 2, "l": 0.5, "c": 1.5, "v": 3}]}})
    fake.route("GET", "/v1beta3/crypto/us/latest/trades", {"trades": {"BTC/USD": {"p": 65000.5}}})
    provider = AlpacaDataProvider("k", "s", client=fake.client())
    bars = provider.get_bars("BTC-USD", "1h", "2d")
    assert len(bars) == 1 and str(bars.index.tz) == "UTC"
    assert provider.get_latest_price("BTC/USD") == 65000.5


def test_data_empty_raises():
    fake = FakeAlpaca()
    fake.route("GET", "/v2/stocks/XYZ/bars", {"bars": None, "next_page_token": None})
    with pytest.raises(DataError):
        AlpacaDataProvider("k", "s", client=fake.client()).get_bars("XYZ", "5m", "5d")
