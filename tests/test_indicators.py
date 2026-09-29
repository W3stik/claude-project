import numpy as np
import pandas as pd
import pytest

from daytrader.analysis import indicators as ind
from daytrader.analysis.levels import opening_range, pivot_points, session_levels

from .conftest import make_bars, make_session_bars


def test_sma_and_ema_basic_values():
    s = pd.Series([1.0, 2.0, 3.0, 4.0, 5.0])
    assert ind.sma(s, 3).tolist()[2:] == [2.0, 3.0, 4.0]
    e = ind.ema(s, 2)
    assert np.isnan(e.iloc[0])
    assert e.iloc[-1] == pytest.approx(4.5, abs=0.1)


def test_rsi_extremes_and_bounds(bars):
    rising = pd.Series(np.arange(1, 60, dtype=float))
    falling = rising[::-1].reset_index(drop=True)
    assert ind.rsi(rising).iloc[-1] == 100
    assert ind.rsi(falling).iloc[-1] == pytest.approx(0, abs=1e-9)
    values = ind.rsi(bars["close"]).dropna()
    assert values.between(0, 100).all()


def test_macd_histogram_is_difference(bars):
    m = ind.macd(bars["close"])
    np.testing.assert_allclose((m["macd"] - m["macd_signal"]).dropna(), m["macd_hist"].dropna())


def test_bollinger_mid_is_sma(bars):
    bb = ind.bollinger(bars["close"], 20, 2)
    np.testing.assert_allclose(bb["bb_mid"].dropna(), ind.sma(bars["close"], 20).dropna())
    assert (bb["bb_upper"].dropna() >= bb["bb_lower"].dropna()).all()


def test_atr_of_constant_range_bars():
    df = make_bars([100.0] * 40, spread=0.5)
    assert ind.atr(df, 14).iloc[-1] == pytest.approx(1.0)


def test_vwap_resets_every_session():
    df = make_session_bars([[100, 101, 102], [110, 111, 112]])
    v = ind.vwap(df)
    typical = (df["high"] + df["low"] + df["close"]) / 3
    first_of_day = df.index.normalize().to_series().diff().ne(pd.Timedelta(0)).to_numpy()
    np.testing.assert_allclose(v[first_of_day], typical[first_of_day])
    assert v.iloc[3] == pytest.approx(typical.iloc[3])


def test_session_relative_volume_is_one_for_identical_days():
    df = make_session_bars([[100] * 10] * 4, volume=500)
    assert ind.session_relative_volume(df) == pytest.approx(1.0)


def test_indicators_have_no_lookahead(bars):
    full = ind.add_indicators(bars)
    cut = ind.add_indicators(bars.iloc[:300])
    columns = ["ema9", "ema21", "rsi", "macd", "bb_upper", "atr", "vwap", "adx", "stoch_k"]
    pd.testing.assert_frame_equal(full[columns].iloc[:300], cut[columns], check_freq=False)


def test_pivot_points_arithmetic():
    p = pivot_points(high=110, low=90, close=100)
    assert p["P"] == pytest.approx(100)
    assert p["R1"] == pytest.approx(110)
    assert p["S1"] == pytest.approx(90)
    assert p["R2"] == pytest.approx(120)
    assert p["S2"] == pytest.approx(80)


def test_session_levels_and_gap():
    df = make_session_bars([[100, 102, 101], [105, 106, 104]])
    levels = session_levels(df)
    assert levels["prev_close"] == 101
    assert levels["prev_high"] == pytest.approx(102.1)
    assert levels["today_open"] == 105
    assert levels["gap_pct"] == pytest.approx((105 / 101 - 1) * 100)


def test_opening_range_uses_first_minutes_of_last_session():
    df = make_session_bars([[100, 101, 102, 103], [200, 205, 210, 190]])
    high, low = opening_range(df, minutes=10)  # first two 5-minute bars
    assert high == pytest.approx(205.1)
    assert low == pytest.approx(199.9)
