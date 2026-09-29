"""Watchlist scanner: rank symbols by what matters intraday (momentum, volume, volatility)."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

import pandas as pd

from .analysis.snapshot import build_snapshot
from .data.base import DataError, DataProvider
from .strategies import Strategy

SCAN_COLUMNS = [
    "symbol", "price", "change_pct", "gap_pct", "rvol", "rsi", "atr_pct", "vs_vwap_pct",
    "trend", "score", "bias", "signal", "error",
]


def _scan_one(provider: DataProvider, symbol: str, interval: str, period: str, strategy: Strategy | None) -> dict:
    row: dict = {"symbol": symbol}
    try:
        bars = provider.get_bars(symbol, interval=interval, period=period)
        snap = build_snapshot(bars, symbol, interval)
    except (DataError, ValueError) as exc:
        row["error"] = str(exc)
        return row
    row.update(
        {
            "price": snap.price,
            "change_pct": snap.change_pct,
            "gap_pct": snap.levels.get("gap_pct"),
            "rvol": snap.rvol,
            "rsi": snap.rsi,
            "atr_pct": snap.atr_pct,
            "vs_vwap_pct": (snap.price / snap.vwap - 1) * 100 if snap.vwap else None,
            "trend": snap.trend,
            "score": snap.score,
            "bias": snap.bias,
        }
    )
    if strategy is not None:
        try:
            signals = strategy.generate_signals(bars)
            row["signal"] = int(signals.iloc[-1])
        except Exception as exc:  # a strategy failing on one symbol must not stop the scan
            row["error"] = f"strategie: {exc}"
    return row


def scan(
    symbols: list[str],
    provider: DataProvider,
    interval: str = "5m",
    period: str = "5d",
    strategy: Strategy | None = None,
    max_workers: int = 8,
) -> pd.DataFrame:
    """Snapshot every symbol in parallel; sorted by the strength of the technical bias."""
    if not symbols:
        return pd.DataFrame(columns=SCAN_COLUMNS)
    with ThreadPoolExecutor(max_workers=min(max_workers, len(symbols))) as pool:
        rows = list(pool.map(lambda s: _scan_one(provider, s, interval, period, strategy), symbols))
    frame = pd.DataFrame(rows).reindex(columns=SCAN_COLUMNS)
    frame["_abs_score"] = frame["score"].abs()
    frame = frame.sort_values(["_abs_score", "rvol"], ascending=False, na_position="last")
    return frame.drop(columns="_abs_score").reset_index(drop=True)
