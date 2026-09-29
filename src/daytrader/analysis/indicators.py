"""Technical indicators on OHLCV DataFrames (columns: open, high, low, close, volume).

Every indicator only uses information available at the bar it is computed for, so the
values can be used for signals at the bar close without lookahead bias.
"""

from __future__ import annotations

import numpy as np
import pandas as pd


def session_keys(index: pd.DatetimeIndex) -> np.ndarray:
    """Calendar date of each bar in the index's own timezone (the exchange's local date)."""
    return np.asarray(index.date)


def sma(series: pd.Series, period: int) -> pd.Series:
    return series.rolling(period, min_periods=period).mean()


def ema(series: pd.Series, period: int) -> pd.Series:
    return series.ewm(span=period, adjust=False, min_periods=period).mean()


def wilder(series: pd.Series, period: int) -> pd.Series:
    """Wilder's smoothing (RMA), used by RSI, ATR and ADX."""
    return series.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()


def rsi(close: pd.Series, period: int = 14) -> pd.Series:
    delta = close.diff()
    gain = wilder(delta.clip(lower=0), period)
    loss = wilder(-delta.clip(upper=0), period)
    rs = gain / loss.replace(0, np.nan)
    out = 100 - 100 / (1 + rs)
    # No losses in the window -> RSI 100; flat price -> 50.
    out = out.mask((loss == 0) & (gain > 0), 100.0)
    out = out.mask((loss == 0) & (gain == 0), 50.0)
    return out.rename("rsi")


def macd(close: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9) -> pd.DataFrame:
    line = ema(close, fast) - ema(close, slow)
    sig = line.ewm(span=signal, adjust=False, min_periods=signal).mean()
    return pd.DataFrame({"macd": line, "macd_signal": sig, "macd_hist": line - sig})


def bollinger(close: pd.Series, period: int = 20, num_std: float = 2.0) -> pd.DataFrame:
    mid = sma(close, period)
    std = close.rolling(period, min_periods=period).std(ddof=0)
    upper = mid + num_std * std
    lower = mid - num_std * std
    width = (upper - lower) / mid
    pct_b = (close - lower) / (upper - lower).replace(0, np.nan)
    return pd.DataFrame(
        {"bb_mid": mid, "bb_upper": upper, "bb_lower": lower, "bb_width": width, "bb_pct_b": pct_b}
    )


def true_range(df: pd.DataFrame) -> pd.Series:
    prev_close = df["close"].shift(1)
    ranges = pd.concat(
        [df["high"] - df["low"], (df["high"] - prev_close).abs(), (df["low"] - prev_close).abs()],
        axis=1,
    )
    return ranges.max(axis=1)


def atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    return wilder(true_range(df), period).rename("atr")


def vwap(df: pd.DataFrame) -> pd.Series:
    """Volume weighted average price, reset at the start of every session (local date)."""
    typical = (df["high"] + df["low"] + df["close"]) / 3
    pv = typical * df["volume"]
    keys = session_keys(df.index)
    cum_pv = pv.groupby(keys).cumsum()
    cum_vol = df["volume"].groupby(keys).cumsum()
    return (cum_pv / cum_vol.replace(0, np.nan)).rename("vwap")


def stochastic(df: pd.DataFrame, k_period: int = 14, d_period: int = 3) -> pd.DataFrame:
    low_min = df["low"].rolling(k_period, min_periods=k_period).min()
    high_max = df["high"].rolling(k_period, min_periods=k_period).max()
    k = 100 * (df["close"] - low_min) / (high_max - low_min).replace(0, np.nan)
    d = k.rolling(d_period, min_periods=d_period).mean()
    return pd.DataFrame({"stoch_k": k, "stoch_d": d})


def obv(df: pd.DataFrame) -> pd.Series:
    direction = np.sign(df["close"].diff()).fillna(0)
    return (direction * df["volume"]).cumsum().rename("obv")


def adx(df: pd.DataFrame, period: int = 14) -> pd.DataFrame:
    up_move = df["high"].diff()
    down_move = -df["low"].diff()
    plus_dm = pd.Series(np.where((up_move > down_move) & (up_move > 0), up_move, 0.0), index=df.index)
    minus_dm = pd.Series(np.where((down_move > up_move) & (down_move > 0), down_move, 0.0), index=df.index)
    tr_smooth = wilder(true_range(df), period)
    plus_di = 100 * wilder(plus_dm, period) / tr_smooth.replace(0, np.nan)
    minus_di = 100 * wilder(minus_dm, period) / tr_smooth.replace(0, np.nan)
    dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan)
    return pd.DataFrame({"plus_di": plus_di, "minus_di": minus_di, "adx": wilder(dx, period)})


def relative_volume(volume: pd.Series, period: int = 20) -> pd.Series:
    """Volume of the bar relative to the average of the previous ``period`` bars."""
    avg = volume.shift(1).rolling(period, min_periods=max(2, period // 2)).mean()
    return (volume / avg.replace(0, np.nan)).rename("rvol")


def session_relative_volume(df: pd.DataFrame, lookback_sessions: int = 10) -> float | None:
    """Cumulative volume of the latest session vs. the average of previous sessions
    at the same bar-of-day (the "RVOL" day traders use to find stocks in play)."""
    if df.empty:
        return None
    keys = session_keys(df.index)
    frame = pd.DataFrame({"session": keys, "volume": df["volume"].to_numpy()})
    frame["bar_no"] = frame.groupby("session").cumcount()
    frame["cum_vol"] = frame.groupby("session")["volume"].cumsum()
    sessions = list(dict.fromkeys(keys))
    if len(sessions) < 2:
        return None
    last_session = sessions[-1]
    today = frame[frame["session"] == last_session]
    bar_no = int(today["bar_no"].iloc[-1])
    today_cum = float(today["cum_vol"].iloc[-1])
    previous = frame[frame["session"].isin(sessions[-1 - lookback_sessions : -1])]
    same_time = previous[previous["bar_no"] == bar_no]["cum_vol"]
    if same_time.empty or same_time.mean() <= 0:
        return None
    return today_cum / float(same_time.mean())


def add_indicators(
    df: pd.DataFrame,
    ema_fast: int = 9,
    ema_slow: int = 21,
    rsi_period: int = 14,
    atr_period: int = 14,
    bb_period: int = 20,
    bb_std: float = 2.0,
) -> pd.DataFrame:
    """Return a copy of ``df`` with the standard indicator columns used across the app."""
    out = df.copy()
    close = out["close"]
    out[f"ema{ema_fast}"] = ema(close, ema_fast)
    out[f"ema{ema_slow}"] = ema(close, ema_slow)
    out["sma50"] = sma(close, 50)
    out["sma200"] = sma(close, 200)
    out["rsi"] = rsi(close, rsi_period)
    out = out.join(macd(close))
    out = out.join(bollinger(close, bb_period, bb_std))
    out["atr"] = atr(out, atr_period)
    out["vwap"] = vwap(out)
    out = out.join(adx(out))
    out = out.join(stochastic(out))
    out["rvol"] = relative_volume(out["volume"])
    return out
