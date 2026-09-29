"""Yahoo Finance via ``yfinance`` - free, no API key, global coverage.

Prague stocks use the ``.PR`` suffix (``CEZ.PR``, ``KOMB.PR``), Xetra ``.DE``, crypto
``BTC-USD``. Yahoo data can be delayed and is unofficial - fine for analysis and
paper trading, not for latency-sensitive execution.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timezone
from typing import Any

import pandas as pd

from ..models import NewsItem, Quote
from .base import DataError, DataProvider, normalize_bars, resolve_range, utcnow

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


def _default_ticker(symbol: str) -> Any:
    import yfinance as yf

    return yf.Ticker(symbol)


class YahooProvider(DataProvider):
    name = "yahoo"
    supports_news = True

    def __init__(self, ticker_factory: Callable[[str], Any] | None = None) -> None:
        self._ticker = ticker_factory or _default_ticker
        self.last_warning: str | None = None

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
            raise DataError(f"Yahoo Finance: chyba při stahování {symbol}: {exc}") from exc
        if raw is None or raw.empty:
            raise DataError(
                f"Yahoo nevrátil data pro {symbol} ({interval}). Zkontroluj symbol "
                "(pražské akcie mají příponu .PR, např. CEZ.PR) nebo zkus jiné období."
            )
        return normalize_bars(raw)

    def get_latest_price(self, symbol: str) -> float:
        ticker = self._ticker(symbol)
        for period in ("1d", "5d"):
            try:
                bars = ticker.history(period=period, interval="1m", prepost=False, auto_adjust=True)
            except Exception:
                bars = None
            if bars is not None and not bars.empty:
                return float(bars["Close"].dropna().iloc[-1])
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
