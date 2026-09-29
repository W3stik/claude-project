from datetime import datetime, timedelta, timezone

import pytest

from daytrader.journal import Journal, daily_pnl, journal_stats, round_trips
from daytrader.models import Fill, Side

T0 = datetime(2026, 9, 21, 14, 0, tzinfo=timezone.utc)


def fill(i, side, qty, price, minutes, symbol="AAPL", fee=0.0):
    return Fill(str(i), None, symbol, side, qty, price, T0 + timedelta(minutes=minutes), fee)


def test_round_trip_long_and_short():
    trips = round_trips([
        fill(1, Side.BUY, 10, 100, 0),
        fill(2, Side.SELL, 10, 101, 5),
        fill(3, Side.SELL, 5, 50, 10, symbol="MSFT"),
        fill(4, Side.BUY, 5, 48, 20, symbol="MSFT"),
    ])
    assert trips["side"].tolist() == ["long", "short"]
    assert trips["pnl"].tolist() == pytest.approx([10.0, 10.0])


def test_round_trip_partial_and_flip_with_fees():
    trips = round_trips([
        fill(1, Side.BUY, 10, 100, 0, fee=1.0),
        fill(2, Side.SELL, 4, 102, 5, fee=0.4),
        fill(3, Side.SELL, 10, 103, 10, fee=1.0),  # closes 6 and opens a 4-share short
        fill(4, Side.BUY, 4, 101, 15),
    ])
    assert trips["qty"].tolist() == [4, 6, 4]
    assert trips["side"].tolist() == ["long", "long", "short"]
    # first leg: 4 * 2 = 8 gross minus fees 4 * (0.1 + 0.1)
    assert trips["pnl"].iloc[0] == pytest.approx(8 - 0.8)
    assert trips["pnl"].iloc[2] == pytest.approx(4 * 2 - 0.4)
    assert journal_stats(trips)["trades"] == 3


def test_daily_pnl_groups_by_local_date():
    trips = round_trips([fill(1, Side.BUY, 1, 10, 0), fill(2, Side.SELL, 1, 12, 5)])
    daily = daily_pnl(trips)
    assert daily.iloc[0] == pytest.approx(2.0)


def test_journal_storage(tmp_path):
    journal = Journal(tmp_path / "j.db")
    journal.log("hello", symbol="AAPL")
    journal.log_order("paper", "AAPL", "buy", 1, "market", 100, reason="entry long", ts=T0)
    journal.log_order("paper", "AAPL", "sell", 1, "market", 101, reason="exit signal", ts=T0)
    assert journal.entries_since(T0 - timedelta(hours=1), "paper") == 1
    assert journal.events(5)["message"].tolist() == ["hello"]
    journal.set_state("BTC/USDT", "long", 100, 95, 110)
    assert journal.get_state("BTC/USDT")["stop"] == 95
    journal.clear_state("BTC/USDT")
    assert journal.get_state("BTC/USDT") is None
