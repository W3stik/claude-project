"""Price levels day traders watch: previous day range, pivot points, opening range."""

from __future__ import annotations

import numpy as np
import pandas as pd

from .indicators import session_keys


def daily_bars(df: pd.DataFrame) -> pd.DataFrame:
    """Aggregate intraday bars to one row per session (local calendar date)."""
    if df.empty:
        return df
    keys = pd.Index(session_keys(df.index), name="session")
    grouped = df.groupby(keys)
    return pd.DataFrame(
        {
            "open": grouped["open"].first(),
            "high": grouped["high"].max(),
            "low": grouped["low"].min(),
            "close": grouped["close"].last(),
            "volume": grouped["volume"].sum(),
        }
    )


def pivot_points(high: float, low: float, close: float) -> dict[str, float]:
    """Classic floor-trader pivots computed from the previous session."""
    p = (high + low + close) / 3
    return {
        "R3": high + 2 * (p - low),
        "R2": p + (high - low),
        "R1": 2 * p - low,
        "P": p,
        "S1": 2 * p - high,
        "S2": p - (high - low),
        "S3": low - 2 * (high - p),
    }


def session_levels(df: pd.DataFrame) -> dict[str, float]:
    """Levels of the latest and the previous session plus pivots (needs >= 2 sessions)."""
    days = daily_bars(df)
    levels: dict[str, float] = {}
    if days.empty:
        return levels
    today = days.iloc[-1]
    levels.update(
        {
            "today_open": float(today["open"]),
            "today_high": float(today["high"]),
            "today_low": float(today["low"]),
        }
    )
    if len(days) >= 2:
        prev = days.iloc[-2]
        levels.update(
            {
                "prev_high": float(prev["high"]),
                "prev_low": float(prev["low"]),
                "prev_close": float(prev["close"]),
                "gap_pct": float((today["open"] / prev["close"] - 1) * 100),
            }
        )
        levels.update({f"pivot_{k}": v for k, v in pivot_points(prev["high"], prev["low"], prev["close"]).items()})
    return levels


def opening_range(df: pd.DataFrame, minutes: int = 15) -> tuple[float, float] | None:
    """High/low of the first ``minutes`` of the latest session."""
    if df.empty:
        return None
    keys = session_keys(df.index)
    last = df[keys == keys[-1]]
    cutoff = last.index[0] + pd.Timedelta(minutes=minutes)
    window = last[last.index < cutoff]
    if window.empty:
        return None
    return float(window["high"].max()), float(window["low"].min())


def swing_levels(df: pd.DataFrame, window: int = 5, max_levels: int = 3) -> dict[str, list[float]]:
    """Nearest swing highs above and swing lows below the last close (simple fractals)."""
    if len(df) < 2 * window + 1:
        return {"resistance": [], "support": []}
    highs = df["high"].to_numpy()
    lows = df["low"].to_numpy()
    last_close = float(df["close"].iloc[-1])
    swing_highs, swing_lows = [], []
    for i in range(window, len(df) - window):
        segment_h = highs[i - window : i + window + 1]
        segment_l = lows[i - window : i + window + 1]
        if highs[i] == segment_h.max():
            swing_highs.append(float(highs[i]))
        if lows[i] == segment_l.min():
            swing_lows.append(float(lows[i]))
    resistance = sorted({round(h, 4) for h in swing_highs if h > last_close})[:max_levels]
    support = sorted({round(low, 4) for low in swing_lows if low < last_close}, reverse=True)[:max_levels]
    return {"resistance": resistance, "support": support}


def nearest_level(price: float, levels: dict[str, float]) -> tuple[str, float] | None:
    if not levels:
        return None
    candidates = {k: v for k, v in levels.items() if k != "gap_pct" and np.isfinite(v)}
    if not candidates:
        return None
    key = min(candidates, key=lambda k: abs(candidates[k] - price))
    return key, candidates[key]
