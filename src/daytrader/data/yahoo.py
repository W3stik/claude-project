"""Yahoo Finance via ``yfinance`` - free, no API key, global coverage.

Prague stocks use the ``.PR`` suffix (``CEZ.PR``, ``KOMB.PR``), Xetra ``.DE``, crypto
``BTC-USD``. Yahoo data can be delayed and is unofficial - fine for analysis and
paper trading, not for latency-sensitive execution.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from datetime import datetime, timezone
from typing import Any

import pandas as pd

from ..models import NewsItem, Quote
from .base import DataError, DataProvider, DataRateLimited, normalize_bars, resolve_range, utcnow

YF_INTERVALS = {
    "1m": "1m",
    "2m": "2m",
    "5m": "5m",
    "15m": "15m",
    "30m": "30m",
    "1h": "60m",
    "60m": "60m",
    "90m": "90m",
    "1d": "1d",
}
# Yahoo only serves limited intraday history.
MAX_LOOKBACK_DAYS = {"1m": 7, "2m": 59, "5m": 59, "15m": 59, "30m": 59, "90m": 59, "60m": 729}
# One bot cycle asks for the same symbol several times (bars, latest price, paper fills).
# Within this window they share one download, which keeps a bot polling every minute well
# below Yahoo's request limits.
CACHE_SECONDS = 20.0
# When Yahoo answers "Too Many Requests", stop asking for a minute (doubling up to 10 minutes).
RATE_LIMIT_PAUSE = 60.0
MAX_RATE_LIMIT_PAUSE = 600.0
RATE_LIMITED = "Yahoo dočasně omezilo počet dotazů – bot to zkusí znovu za chvíli."


def _is_rate_limit(exc: Exception) -> bool:
    text = f"{type(exc).__name__} {exc}".lower()
    return "ratelimit" in text or "rate limit" in text or "too many requests" in text


def _default_ticker(symbol: str) -> Any:
    import yfinance as yf

    return yf.Ticker(symbol)


class YahooProvider(DataProvider):
    name = "yahoo"
    supports_news = True
    parallel_requests = 8  # yfinance downloads tickers in threads itself

    def __init__(
        self, ticker_factory: Callable[[str], Any] | None = None, clock: Callable[[], float] = time.monotonic
    ) -> None:
        self._ticker = ticker_factory or _default_ticker
        self._clock = clock
        # (symbol, interval) -> (downloaded at, requested start, bars up to the download)
        self._recent: dict[tuple[str, str], tuple[float, pd.Timestamp, pd.DataFrame]] = {}
        self._lock = threading.Lock()
        self._pause = 0.0
        self._paused_until = float("-inf")
        self.last_warning: str | None = None

    def _check_pause(self) -> None:
        if self._clock() < self._paused_until:
            raise DataRateLimited(RATE_LIMITED)

    def _pause_after(self, exc: Exception) -> DataRateLimited:
        with self._lock:
            if self._clock() >= self._paused_until:  # parallel downloads hit the limit together
                self._pause = min(MAX_RATE_LIMIT_PAUSE, self._pause * 2) if self._pause else RATE_LIMIT_PAUSE
                self._paused_until = self._clock() + self._pause
        return DataRateLimited(RATE_LIMITED)

    def _recent_bars(self, symbol: str, yf_interval: str) -> tuple[pd.Timestamp, pd.DataFrame] | None:
        entry = self._recent.get((symbol.upper(), yf_interval))
        if entry is None or self._clock() - entry[0] > CACHE_SECONDS:
            return None
        return entry[1], entry[2]

    def get_bars(
        self,
        symbol: str,
        interval: str = "5m",
        period: str = "5d",
        start: datetime | str | None = None,
        end: datetime | str | None = None,
    ) -> pd.DataFrame:
        yf_interval = YF_INTERVALS.get(interval)
        if yf_interval is None:
            raise DataError(f"Yahoo nepodporuje interval {interval}. Použij {', '.join(YF_INTERVALS)}.")
        start_ts, end_ts = resolve_range(period, start, end)
        self.last_warning = None
        max_days = MAX_LOOKBACK_DAYS.get(yf_interval)
        if max_days is not None:
            earliest = pd.Timestamp(utcnow()) - pd.Timedelta(days=max_days)
            if start_ts < earliest:
                start_ts = earliest
                self.last_warning = (
                    f"Yahoo poskytuje interval {interval} jen za posledních {max_days} dní – období bylo zkráceno."
                )
        up_to_now = end is None or end_ts >= pd.Timestamp(utcnow())
        recent = self._recent_bars(symbol, yf_interval) if up_to_now else None
        if recent is not None and recent[0] <= start_ts:
            bars = recent[1][(recent[1].index >= start_ts) & (recent[1].index <= end_ts)]
            if not bars.empty:
                return bars
        self._check_pause()
        kwargs: dict[str, Any] = {
            "interval": yf_interval,
            "start": int(start_ts.timestamp()),
            "auto_adjust": True,
            "prepost": False,
        }
        if end is not None:
            kwargs["end"] = int(end_ts.timestamp())
        try:
            raw = self._ticker(symbol).history(**kwargs)
        except Exception as exc:  # yfinance raises many different exception types
            if _is_rate_limit(exc):
                raise self._pause_after(exc) from exc
            raise DataError(f"Yahoo Finance: chyba při stahování {symbol}: {exc}") from exc
        self._pause = 0.0
        if raw is None or raw.empty:
            raise DataError(
                f"Yahoo nevrátil data pro {symbol} ({interval}). Zkontroluj symbol "
                "(pražské akcie mají příponu .PR, např. CEZ.PR) nebo zkus jiné období."
            )
        bars = normalize_bars(raw)
        if up_to_now:
            self._recent[(symbol.upper(), yf_interval)] = (self._clock(), start_ts, bars.copy())
        return bars

    def get_latest_price(self, symbol: str) -> float:
        for yf_interval in ("1m", "2m", "5m", "15m", "30m", "60m", "90m"):
            recent = self._recent_bars(symbol, yf_interval)
            if recent is not None and not recent[1].empty:
                return float(recent[1]["close"].iloc[-1])  # close of the bar still forming = last trade
        self._check_pause()
        ticker = self._ticker(symbol)
        for period in ("1d", "5d"):
            try:
                bars = ticker.history(period=period, interval="1m", prepost=False, auto_adjust=True)
            except Exception as exc:
                if _is_rate_limit(exc):
                    raise self._pause_after(exc) from exc
                bars = None
            if bars is None or bars.empty:
                continue
            try:
                frame = normalize_bars(bars)
            except DataError:
                continue
            if not frame.empty:
                self._recent[(symbol.upper(), "1m")] = (self._clock(), frame.index[0], frame)
                return float(frame["close"].iloc[-1])
        try:
            price = ticker.fast_info.last_price
        except Exception as exc:
            raise DataError(f"Nepodařilo se zjistit cenu {symbol}: {exc}") from exc
        if price is None:
            raise DataError(f"Nepodařilo se zjistit cenu {symbol}.")
        return float(price)

    def get_quote(self, symbol: str) -> Quote:
        ticker = self._ticker(symbol)
        try:
            info = ticker.fast_info
            price = info.last_price
            prev = info.previous_close
            high, low, currency = info.day_high, info.day_low, info.currency
        except Exception as exc:
            raise DataError(f"Nepodařilo se načíst kotaci {symbol}: {exc}") from exc
        if price is None:
            raise DataError(f"Yahoo nezná symbol {symbol}.")
        return Quote(
            symbol=symbol,
            price=float(price),
            previous_close=float(prev) if prev else None,
            day_high=float(high) if high else None,
            day_low=float(low) if low else None,
            currency=currency,
            timestamp=datetime.now(timezone.utc),
        )

    def get_news(self, symbol: str, limit: int = 10) -> list[NewsItem]:
        try:
            raw = self._ticker(symbol).get_news(count=limit)
        except Exception:
            return []
        items = []
        for article in raw or []:
            item = parse_yahoo_news(article)
            if item is not None:
                items.append(item)
        return items[:limit]


def parse_yahoo_news(article: dict[str, Any]) -> NewsItem | None:
    """Handle both the current (``content`` wrapper) and the legacy flat news format."""
    content = article.get("content") if isinstance(article.get("content"), dict) else article
    title = content.get("title")
    if not title:
        return None
    provider = content.get("provider")
    source = provider.get("displayName") if isinstance(provider, dict) else content.get("publisher")
    url = None
    for key in ("canonicalUrl", "clickThroughUrl"):
        value = content.get(key)
        if isinstance(value, dict) and value.get("url"):
            url = value["url"]
            break
    url = url or content.get("link")
    published = None
    if content.get("pubDate"):
        published = pd.Timestamp(content["pubDate"]).to_pydatetime()
    elif content.get("providerPublishTime"):
        published = datetime.fromtimestamp(int(content["providerPublishTime"]), tz=timezone.utc)
    return NewsItem(title=title, source=source, url=url, published=published, summary=content.get("summary"))
