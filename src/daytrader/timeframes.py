"""Parsing of bar intervals ("5m", "1h", "1d") and lookback periods ("5d", "3mo")."""

from __future__ import annotations

import re
from datetime import datetime, timezone

import pandas as pd

INTERVALS = ["1m", "2m", "5m", "15m", "30m", "1h", "1d"]
PERIODS = ["1d", "5d", "7d", "1mo", "2mo", "3mo", "6mo", "1y", "2y", "5y"]

_INTERVAL_RE = re.compile(r"^(\d+)\s*(m|min|h|d)$", re.IGNORECASE)
_PERIOD_RE = re.compile(r"^(\d+)\s*(d|w|wk|mo|y)$", re.IGNORECASE)


def parse_interval(interval: str) -> tuple[int, str]:
    """Return ``(amount, unit)`` where unit is one of ``m``, ``h``, ``d``."""
    match = _INTERVAL_RE.match(interval.strip())
    if not match:
        raise ValueError(f"Neznámý interval '{interval}'. Použij např. 1m, 5m, 15m, 1h, 1d.")
    amount, unit = int(match.group(1)), match.group(2).lower()
    if unit == "min":
        unit = "m"
    if amount <= 0:
        raise ValueError("Interval musí být kladný.")
    return amount, unit


def interval_seconds(interval: str) -> int:
    amount, unit = parse_interval(interval)
    return amount * {"m": 60, "h": 3600, "d": 86400}[unit]


def interval_timedelta(interval: str) -> pd.Timedelta:
    return pd.Timedelta(seconds=interval_seconds(interval))


def is_intraday(interval: str) -> bool:
    return parse_interval(interval)[1] != "d"


def pandas_freq(interval: str) -> str:
    amount, unit = parse_interval(interval)
    return {"m": f"{amount}min", "h": f"{amount}h", "d": f"{amount}D"}[unit]


def parse_period(period: str, now: datetime | None = None) -> pd.Timedelta:
    """Convert a lookback such as ``5d``, ``2wk``, ``3mo``, ``1y`` or ``ytd`` to a timedelta."""
    period = period.strip().lower()
    if period == "ytd":
        now = now or datetime.now(timezone.utc)
        start = datetime(now.year, 1, 1, tzinfo=now.tzinfo)
        return pd.Timedelta(now - start)
    match = _PERIOD_RE.match(period)
    if not match:
        raise ValueError(f"Neznámé období '{period}'. Použij např. 5d, 1mo, 3mo, 1y.")
    amount, unit = int(match.group(1)), match.group(2)
    days = {"d": 1, "w": 7, "wk": 7, "mo": 30, "y": 365}[unit] * amount
    return pd.Timedelta(days=days)


def floor_time(ts: pd.Timestamp, interval: str) -> pd.Timestamp:
    """Floor a timestamp to the start of the bar that contains it."""
    return ts.floor(pandas_freq(interval)) if is_intraday(interval) else ts.normalize()
