"""Alpaca market data (US stocks/ETFs and crypto). Free plan = IEX feed."""

from __future__ import annotations

from datetime import datetime
from typing import Any

import httpx
import pandas as pd

from ..alpaca_common import DATA_URL, AlpacaHTTP, alpaca_timeframe, rfc3339
from ..models import NewsItem, Quote
from ..sessions import SESSIONS, filter_regular_hours, is_crypto_symbol
from ..timeframes import is_intraday
from .base import DataError, DataProvider, normalize_bars, resolve_range


def _crypto_pair(symbol: str) -> str:
    symbol = symbol.upper()
    if "/" in symbol:
        return symbol
    if "-" in symbol:  # BTC-USD -> BTC/USD
        return symbol.replace("-", "/")
    return symbol


class AlpacaDataProvider(DataProvider):
    name = "alpaca"
    supports_news = True
    parallel_requests = 4

    def __init__(
        self,
        api_key: str,
        secret_key: str,
        feed: str = "iex",
        regular_hours_only: bool = True,
        client: httpx.Client | None = None,
    ) -> None:
        self.http = AlpacaHTTP(DATA_URL, api_key, secret_key, client=client, error_cls=DataError)
        self.feed = feed
        self.regular_hours_only = regular_hours_only

    def _paginate(self, path: str, params: dict[str, Any], extract) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        page_token = None
        for _ in range(100):  # hard cap to avoid endless loops
            query = dict(params)
            if page_token:
                query["page_token"] = page_token
            payload = self.http.request("GET", path, params=query) or {}
            rows.extend(extract(payload) or [])
            page_token = payload.get("next_page_token")
            if not page_token:
                break
        return rows

    def get_bars(
        self,
        symbol: str,
        interval: str = "5m",
        period: str = "5d",
        start: datetime | str | None = None,
        end: datetime | str | None = None,
    ) -> pd.DataFrame:
        start_ts, end_ts = resolve_range(period, start, end)
        params: dict[str, Any] = {
            "timeframe": alpaca_timeframe(interval),
            "start": rfc3339(start_ts),
            "limit": 10000,
            "sort": "asc",
        }
        if end is not None:
            params["end"] = rfc3339(end_ts)

        crypto = is_crypto_symbol(symbol)
        if crypto:
            pair = _crypto_pair(symbol)
            params["symbols"] = pair
            rows = self._paginate(
                "/v1beta3/crypto/us/bars", params, lambda p: (p.get("bars") or {}).get(pair)
            )
        else:
            params.update({"adjustment": "split", "feed": self.feed})
            rows = self._paginate(f"/v2/stocks/{symbol.upper()}/bars", params, lambda p: p.get("bars"))

        if not rows:
            raise DataError(f"Alpaca nevrátila data pro {symbol} ({interval}).")
        frame = pd.DataFrame(rows)
        frame.index = pd.to_datetime(frame["t"], utc=True)
        frame = frame.rename(columns={"o": "open", "h": "high", "l": "low", "c": "close", "v": "volume"})
        bars = normalize_bars(frame)
        if crypto:
            return bars
        bars.index = bars.index.tz_convert("America/New_York")
        if self.regular_hours_only and is_intraday(interval):
            bars = filter_regular_hours(bars, SESSIONS["us"])
        return bars

    def get_latest_price(self, symbol: str) -> float:
        if is_crypto_symbol(symbol):
            pair = _crypto_pair(symbol)
            payload = self.http.request("GET", "/v1beta3/crypto/us/latest/trades", params={"symbols": pair})
            trade = (payload or {}).get("trades", {}).get(pair)
        else:
            payload = self.http.request(
                "GET", f"/v2/stocks/{symbol.upper()}/trades/latest", params={"feed": self.feed}
            )
            trade = (payload or {}).get("trade")
        if not trade or trade.get("p") is None:
            raise DataError(f"Alpaca nezná poslední obchod pro {symbol}.")
        return float(trade["p"])

    def get_quote(self, symbol: str) -> Quote:
        if is_crypto_symbol(symbol):
            pair = _crypto_pair(symbol)
            payload = self.http.request("GET", "/v1beta3/crypto/us/snapshots", params={"symbols": pair})
            snap = (payload or {}).get("snapshots", {}).get(pair) or {}
        else:
            snap = self.http.request(
                "GET", f"/v2/stocks/{symbol.upper()}/snapshot", params={"feed": self.feed}
            ) or {}
        trade = snap.get("latestTrade") or {}
        daily = snap.get("dailyBar") or {}
        prev = snap.get("prevDailyBar") or {}
        price = trade.get("p") or daily.get("c")
        if price is None:
            raise DataError(f"Alpaca nevrátila kotaci pro {symbol}.")
        return Quote(
            symbol=symbol,
            price=float(price),
            previous_close=float(prev["c"]) if prev.get("c") else None,
            day_high=float(daily["h"]) if daily.get("h") else None,
            day_low=float(daily["l"]) if daily.get("l") else None,
            currency="USD",
            timestamp=pd.Timestamp(trade["t"]).to_pydatetime() if trade.get("t") else None,
        )

    def get_news(self, symbol: str, limit: int = 10) -> list[NewsItem]:
        try:
            payload = self.http.request(
                "GET",
                "/v1beta1/news",
                params={"symbols": symbol.upper().replace("/", ""), "limit": limit, "sort": "desc"},
            )
        except DataError:
            return []
        items = []
        for article in (payload or {}).get("news", []):
            items.append(
                NewsItem(
                    title=article.get("headline", ""),
                    source=article.get("source") or article.get("author"),
                    url=article.get("url"),
                    published=pd.Timestamp(article["created_at"]).to_pydatetime()
                    if article.get("created_at")
                    else None,
                    summary=article.get("summary") or None,
                )
            )
        return items
