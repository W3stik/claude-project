"""Data provider interface and helpers shared by all market-data sources."""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime, timezone

import pandas as pd

from ..models import NewsItem, Quote
from ..timeframes import interval_timedelta, parse_period

OHLCV = ["open", "high", "low", "close", "volume"]


class DataError(RuntimeError):
    """Market data could not be retrieved or was empty."""


class DataRateLimited(DataError):
    """The data source refuses requests for a while (too many of them)."""


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def to_utc(value: datetime | str | pd.Timestamp) -> pd.Timestamp:
    ts = pd.Timestamp(value)
    return ts.tz_localize("UTC") if ts.tzinfo is None else ts.tz_convert("UTC")


def resolve_range(
    period: str | None,
    start: datetime | str | None = None,
    end: datetime | str | None = None,
    now: datetime | None = None,
) -> tuple[pd.Timestamp, pd.Timestamp]:
    """Turn ``period``/``start``/``end`` arguments into an explicit UTC ``[start, end]`` range."""
    end_ts = to_utc(end) if end is not None else to_utc(now or utcnow())
    if start is not None:
        start_ts = to_utc(start)
    else:
        start_ts = end_ts - parse_period(period or "5d", now=end_ts.to_pydatetime())
    if start_ts >= end_ts:
        raise DataError("Začátek období musí být před jeho koncem.")
    return start_ts, end_ts


def normalize_bars(df: pd.DataFrame) -> pd.DataFrame:
    """Lower-case OHLCV columns, float dtype, tz-aware sorted unique DatetimeIndex."""
    if df is None or df.empty:
        return pd.DataFrame(columns=OHLCV, index=pd.DatetimeIndex([], tz="UTC"))
    out = df.rename(columns={c: str(c).lower() for c in df.columns})
    missing = [c for c in ["open", "high", "low", "close"] if c not in out.columns]
    if missing:
        raise DataError(f"V datech chybí sloupce: {', '.join(missing)}")
    if "volume" not in out.columns:
        out["volume"] = 0.0
    out = out[OHLCV].astype(float)
    out["volume"] = out["volume"].fillna(0.0)
    out = out.dropna(subset=["open", "high", "low", "close"])
    index = pd.DatetimeIndex(out.index)
    if index.tz is None:
        index = index.tz_localize("UTC")
    out.index = index
    out = out[~out.index.duplicated(keep="last")].sort_index()
    out.index.name = "time"
    return out


def drop_incomplete_bar(bars: pd.DataFrame, interval: str, now: datetime | None = None) -> pd.DataFrame:
    """Remove the last bar if it is still forming (its end lies in the future)."""
    if bars.empty:
        return bars
    now_ts = to_utc(now or utcnow())
    last_start = bars.index[-1].tz_convert("UTC")
    if last_start + interval_timedelta(interval) > now_ts:
        return bars.iloc[:-1]
    return bars


def resample_bars(bars: pd.DataFrame, rule: str, offset: pd.Timedelta | None = None) -> pd.DataFrame:
    agg = {"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"}
    kwargs = {"label": "left", "closed": "left", "origin": "start_day"}
    if offset is not None:
        kwargs["offset"] = offset
    out = bars.resample(rule, **kwargs).agg(agg)
    return out.dropna(subset=["open", "high", "low", "close"])


class DataProvider(ABC):
    """Common interface for market data sources."""

    name: str = "base"
    supports_news: bool = False
    #: How many symbols may be downloaded at the same time (the bot fetches in parallel).
    parallel_requests: int = 1

    @abstractmethod
    def get_bars(
        self,
        symbol: str,
        interval: str = "5m",
        period: str = "5d",
        start: datetime | str | None = None,
        end: datetime | str | None = None,
    ) -> pd.DataFrame:
        """Return OHLCV bars with a tz-aware DatetimeIndex (bar start times)."""

    def get_latest_price(self, symbol: str) -> float:
        for interval, period in (("1m", "2d"), ("1d", "10d")):
            try:
                bars = self.get_bars(symbol, interval=interval, period=period)
            except DataError:
                continue
            if not bars.empty:
                return float(bars["close"].iloc[-1])
        raise DataError(f"Nepodařilo se zjistit aktuální cenu {symbol}.")

    def get_quote(self, symbol: str) -> Quote:
        daily = self.get_bars(symbol, interval="1d", period="10d")
        if daily.empty:
            raise DataError(f"Žádná data pro {symbol}.")
        last = daily.iloc[-1]
        try:
            price = self.get_latest_price(symbol)
        except DataError:
            price = float(last["close"])
        prev_close = float(daily["close"].iloc[-2]) if len(daily) > 1 else None
        return Quote(
            symbol=symbol,
            price=price,
            previous_close=prev_close,
            day_high=float(last["high"]),
            day_low=float(last["low"]),
            timestamp=daily.index[-1].to_pydatetime(),
        )

    def get_news(self, symbol: str, limit: int = 10) -> list[NewsItem]:
        return []
