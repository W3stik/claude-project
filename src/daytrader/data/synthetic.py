"""Deterministic synthetic market data ("demo" provider).

Useful for trying the app offline, for tests and for sanity-checking strategies on data
with no real edge. The same symbol always produces the same history, and prices are
consistent across intervals (all bars are aggregated from one 1-minute path).
"""

from __future__ import annotations

import zlib
from collections.abc import Callable
from datetime import date, datetime, timedelta

import numpy as np
import pandas as pd

from ..sessions import MarketSession, session_for_symbol
from ..timeframes import is_intraday, pandas_freq, parse_interval
from .base import DataError, DataProvider, normalize_bars, resample_bars, resolve_range, to_utc, utcnow

ANCHOR = date(2022, 1, 3)


def _seed(*parts: object) -> int:
    return zlib.crc32("|".join(map(str, parts)).encode())


class SyntheticProvider(DataProvider):
    name = "demo"

    def __init__(
        self,
        now: Callable[[], datetime] | None = None,
        daily_vol: float = 0.02,
        daily_drift: float = 0.0002,
    ) -> None:
        self._now = now or utcnow
        self.daily_vol = daily_vol
        self.daily_drift = daily_drift
        self._daily_cache: dict[str, tuple[date, pd.Series]] = {}
        self._minute_cache: dict[tuple[str, date], pd.DataFrame] = {}

    # -- path generation -----------------------------------------------------
    def _trading_days(self, session: MarketSession, until: date) -> pd.DatetimeIndex:
        freq = "B" if session.weekdays_only else "D"
        return pd.date_range(ANCHOR, until, freq=freq)

    def _daily_closes(self, symbol: str, session: MarketSession) -> pd.Series:
        until = to_utc(self._now()).date() + timedelta(days=2)
        cached = self._daily_cache.get(symbol)
        if cached is not None and cached[0] == until:  # extend the path when the clock moves on a day
            return cached[1]
        rng = np.random.default_rng(_seed(symbol, "daily"))
        days = self._trading_days(session, until)
        base = 20 + (_seed(symbol, "base") % 480)
        returns = rng.normal(self.daily_drift, self.daily_vol, len(days))
        closes = pd.Series(base * np.exp(np.cumsum(returns)), index=days)
        self._daily_cache[symbol] = (until, closes)
        return closes

    def _minute_bars(self, symbol: str, day: pd.Timestamp, session: MarketSession) -> pd.DataFrame:
        key = (symbol, day.date())
        if key in self._minute_cache:
            return self._minute_cache[key]
        closes = self._daily_closes(symbol, session)
        pos = closes.index.get_loc(day)
        close = float(closes.iloc[pos])
        prev_close = float(closes.iloc[pos - 1]) if pos > 0 else close
        rng = np.random.default_rng(_seed(symbol, day.date()))

        if session.is_24h:
            start_local = pd.Timestamp(day.date(), tz=session.tz)
            n = 24 * 60
        else:
            start_local = pd.Timestamp(datetime.combine(day.date(), session.open), tz=session.tz)
            end_local = pd.Timestamp(datetime.combine(day.date(), session.close), tz=session.tz)
            n = int((end_local - start_local).total_seconds() // 60)

        gap = 0.0 if session.is_24h else rng.normal(0, self.daily_vol * 0.3)
        open_price = prev_close * np.exp(gap)
        x = np.linspace(0, 1, n)
        profile = 1 + 1.5 * (2 * x - 1) ** 2  # U-shaped intraday volatility
        sigma = self.daily_vol / np.sqrt(n) * profile / np.sqrt(np.mean(profile**2))
        steps = rng.normal(0, sigma)
        walk = np.cumsum(steps)
        target = np.log(close / open_price)
        bridge = walk - x * (walk[-1] - target)  # Brownian bridge: ends exactly at the daily close
        close_px = open_price * np.exp(bridge)
        open_px = np.concatenate([[open_price], close_px[:-1]])
        wick = np.abs(rng.normal(0, sigma * 0.6))
        high_px = np.maximum(open_px, close_px) * np.exp(wick)
        low_px = np.minimum(open_px, close_px) * np.exp(-np.abs(rng.normal(0, sigma * 0.6)))
        base_volume = 200_000 + (_seed(symbol, "vol") % 3_000_000)
        volume = base_volume / n * profile * rng.lognormal(0, 0.35, n)

        index = start_local + pd.to_timedelta(np.arange(n), unit="min")
        frame = pd.DataFrame(
            {"open": open_px, "high": high_px, "low": low_px, "close": close_px, "volume": np.round(volume)},
            index=index,
        )
        self._minute_cache[key] = frame
        return frame

    # -- public API -------------------------------------------------------------
    def get_bars(
        self,
        symbol: str,
        interval: str = "5m",
        period: str = "5d",
        start: datetime | str | None = None,
        end: datetime | str | None = None,
    ) -> pd.DataFrame:
        symbol = symbol.upper()
        session = session_for_symbol(symbol)
        now = to_utc(self._now())
        start_ts, end_ts = resolve_range(period, start, end, now=now.to_pydatetime())
        end_ts = min(end_ts, now)
        amount, unit = parse_interval(interval)

        days = self._trading_days(session, end_ts.tz_convert(session.tz).date())
        first_day = start_ts.tz_convert(session.tz).normalize().tz_localize(None)
        days = days[days >= first_day]
        if len(days) == 0:
            raise DataError(f"Demo data pro {symbol} v zadaném období nejsou (víkend/svátek?).")

        if not is_intraday(interval):
            if amount != 1:
                raise DataError("Demo data podporují z denních intervalů jen 1d.")
            rows = []
            for day in days:
                minutes = self._minute_bars(symbol, day, session)
                minutes = minutes[minutes.index <= end_ts]
                if minutes.empty:
                    continue
                rows.append(
                    {
                        "time": pd.Timestamp(day.date(), tz=session.tz),
                        "open": minutes["open"].iloc[0],
                        "high": minutes["high"].max(),
                        "low": minutes["low"].min(),
                        "close": minutes["close"].iloc[-1],
                        "volume": minutes["volume"].sum(),
                    }
                )
            daily = pd.DataFrame(rows).set_index("time") if rows else pd.DataFrame()
            return normalize_bars(daily)

        frames = [self._minute_bars(symbol, day, session) for day in days]
        minutes = pd.concat(frames)
        minutes = minutes[(minutes.index >= start_ts) & (minutes.index <= end_ts)]
        if minutes.empty:
            raise DataError(f"Demo data pro {symbol} v zadaném období nejsou.")
        if (amount, unit) == (1, "m"):
            return normalize_bars(minutes)
        open_minutes = 0 if session.is_24h else session.open.hour * 60 + session.open.minute
        step = amount * (60 if unit == "h" else 1)
        offset = pd.Timedelta(minutes=open_minutes % step)
        return normalize_bars(resample_bars(minutes, pandas_freq(interval), offset=offset))

    def get_latest_price(self, symbol: str) -> float:
        bars = self.get_bars(symbol, interval="1m", period="7d")
        return float(bars["close"].iloc[-1])
