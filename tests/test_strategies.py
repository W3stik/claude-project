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
