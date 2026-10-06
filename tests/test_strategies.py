import pandas as pd
import pytest

from daytrader.strategies import STRATEGIES, get_strategy, positions_from_events

from .conftest import make_session_bars


@pytest.mark.parametrize("key", list(STRATEGIES))
def test_signals_are_valid_and_aligned(key, bars):
    signals = get_strategy(key).generate_signals(bars)
    assert signals.index.equals(bars.index)
    assert set(signals.unique()) <= {-1, 0, 1}


@pytest.mark.parametrize("key", list(STRATEGIES))
def test_no_lookahead(key, bars):
    """A signal at bar t must not change when future bars are added."""
    strategy = get_strategy(key)
    full = strategy.generate_signals(bars)
    for cut in (150, 400, len(bars) - 7):
        partial = strategy.generate_signals(bars.iloc[:cut])
        pd.testing.assert_series_equal(full.iloc[:cut], partial, check_names=False, check_freq=False)


def test_parameter_validation():
    with pytest.raises(ValueError):
        get_strategy("ema_cross", fast=30, slow=10)
    with pytest.raises(ValueError):
        get_strategy("ema_cross", nonsense=1)
    with pytest.raises(ValueError):
        get_strategy("unknown")
    strategy = get_strategy("rsi_reversion", period="7", lower="25")
    assert strategy.params["period"] == 7 and strategy.params["lower"] == 25.0


def test_positions_from_events_state_machine():
    idx = range(8)
    le = pd.Series([0, 1, 0, 0, 0, 0, 0, 0], index=idx).astype(bool)
    lx = pd.Series([0, 0, 0, 1, 0, 0, 0, 0], index=idx).astype(bool)
    se = pd.Series([0, 0, 0, 0, 0, 1, 0, 0], index=idx).astype(bool)
    sx = pd.Series([0, 0, 0, 0, 0, 0, 0, 1], index=idx).astype(bool)
    assert positions_from_events(le, lx, se, sx).tolist() == [0, 1, 1, 0, 0, -1, -1, 0]


def test_orb_enters_only_after_opening_range():
    day = [100, 101, 100.5] + [101, 103, 104, 104, 104]  # OR = first 15 min (3 bars)
    bars = make_session_bars([day, day])
    signals = get_strategy("orb", minutes=15).generate_signals(bars)
    first_day = signals.iloc[:8].tolist()
    assert first_day[:3] == [0, 0, 0]  # no trading inside the opening range
    assert first_day[4] == 1  # close 103 > OR high
    assert signals.iloc[8] == 0  # state resets the next day


def test_orb_respects_max_entries():
    day = [100, 100, 100, 102, 99.5, 102, 102]
    bars = make_session_bars([day], spread=0.2)
    signals = get_strategy("orb", minutes=15, max_entries=1).generate_signals(bars).tolist()
    assert signals[3] == 1 and signals[4] == 0 and signals[5] == 0


def test_scalp_trades_follow_its_rules(demo):
    from daytrader.analysis.indicators import ema, rsi, session_keys, vwap

    bars = demo.get_bars("AAPL", "1m", "5d")
    signals = get_strategy("scalp", max_hold=7).generate_signals(bars).to_numpy()
    close = bars["close"].to_numpy()
    v = vwap(bars).to_numpy()
    fast, slow = ema(bars["close"], 20).to_numpy(), ema(bars["close"], 50).to_numpy()
    r = rsi(bars["close"], 5).to_numpy()
    keys = session_keys(bars.index)
    trades = held = 0
    for i in range(1, len(bars)):
        same_session = keys[i] == keys[i - 1]
        if signals[i] == 1 and (signals[i - 1] != 1 or not same_session):
            trades, held = trades + 1, 1
            assert close[i] > v[i] and fast[i] > slow[i] and r[i - 1] < 35 <= r[i]  # a dip in an uptrend
        elif signals[i] == 1:
            held += 1
        elif signals[i - 1] == 1 and same_session:  # long closed: profit target, below VWAP or time is up
            assert r[i] >= 65 or close[i] < v[i] or held == 7
        assert held <= 7 or signals[i] != 1
    assert trades >= 15  # several trades a day


def test_scalp_backtest_keeps_trades_short(demo):
    from daytrader.backtest.engine import BacktestConfig, run_backtest

    bars = demo.get_bars("MSFT", "1m", "5d")
    result = run_backtest(bars, get_strategy("scalp", max_hold=10), BacktestConfig(), interval="1m")
    trades = result.trades_df()
    assert len(trades) >= 15
    assert trades["bars_held"].max() <= 11  # entry bar + at most 10 more
    assert set(trades["exit_reason"]) <= {"signal", "stop", "target", "eod"}
