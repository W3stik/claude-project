"""Crypto market data from 100+ exchanges through the CCXT library (public data needs no key)."""

from __future__ import annotations

from datetime import datetime
from typing import Any

import pandas as pd

from ..models import Quote
from ..timeframes import interval_seconds
from .base import DataError, DataProvider, normalize_bars, resolve_range


def create_exchange(
    exchange_id: str,
    api_key: str | None = None,
    secret: str | None = None,
    password: str | None = None,
    sandbox: bool = False,
) -> Any:
    try:
        import ccxt
    except ImportError as exc:  # pragma: no cover - depends on optional extra
        raise DataError("Pro kryptoburzy nainstaluj CCXT: pip install 'daytrader[crypto]'") from exc
    if not hasattr(ccxt, exchange_id):
        raise DataError(f"CCXT nezná burzu '{exchange_id}'. Příklady: binance, kraken, coinbase, bybit, coinmate.")
    config: dict[str, Any] = {"enableRateLimit": True}
    if api_key:
        config["apiKey"] = api_key
    if secret:
        config["secret"] = secret
    if password:
        config["password"] = password
    exchange = getattr(ccxt, exchange_id)(config)
    exchange.options["warnOnFetchOpenOrdersWithoutSymbol"] = False
    if sandbox:
        try:
            exchange.set_sandbox_mode(True)
        except Exception as exc:
            raise DataError(f"Burza {exchange_id} nemá testnet (sandbox) v CCXT: {exc}") from exc
    return exchange


def normalize_pair(symbol: str) -> str:
    """Accept ``BTC/USDT`` as well as Yahoo style ``BTC-USDT``."""
    return symbol.upper().replace("-", "/")


class CCXTDataProvider(DataProvider):
    name = "ccxt"

    def __init__(self, exchange: Any) -> None:
        self.exchange = exchange

    def get_bars(
        self,
        symbol: str,
        interval: str = "5m",
        period: str = "5d",
        start: datetime | str | None = None,
        end: datetime | str | None = None,
    ) -> pd.DataFrame:
        pair = normalize_pair(symbol)
        timeframes = getattr(self.exchange, "timeframes", None) or {}
        if timeframes and interval not in timeframes:
            raise DataError(f"Burza {self.exchange.id} nepodporuje interval {interval}.")
        start_ts, end_ts = resolve_range(period, start, end)
        since = int(start_ts.timestamp() * 1000)
        end_ms = int(end_ts.timestamp() * 1000)
        step_ms = interval_seconds(interval) * 1000
        rows: list[list[float]] = []
        for _ in range(200):  # safety cap on pagination
            try:
                batch = self.exchange.fetch_ohlcv(pair, timeframe=interval, since=since, limit=1000)
            except Exception as exc:
                raise DataError(f"{self.exchange.id}: nepodařilo se stáhnout {pair}: {exc}") from exc
            if not batch:
                break
            rows.extend(batch)
            last = int(batch[-1][0])
            if last >= end_ms or len(batch) < 2:
                break
            since = last + step_ms
        if not rows:
            raise DataError(f"{self.exchange.id} nevrátila data pro {pair}.")
        frame = pd.DataFrame(rows, columns=["t", "open", "high", "low", "close", "volume"])
        frame = frame[frame["t"] <= end_ms]
        frame.index = pd.to_datetime(frame["t"], unit="ms", utc=True)
        return normalize_bars(frame)

    def get_latest_price(self, symbol: str) -> float:
        pair = normalize_pair(symbol)
        try:
            ticker = self.exchange.fetch_ticker(pair)
        except Exception as exc:
            raise DataError(f"{self.exchange.id}: nepodařilo se načíst cenu {pair}: {exc}") from exc
        price = ticker.get("last") or ticker.get("close")
        if price is None:
            raise DataError(f"{self.exchange.id}: žádná cena pro {pair}.")
        return float(price)

    def get_quote(self, symbol: str) -> Quote:
        pair = normalize_pair(symbol)
        try:
            ticker = self.exchange.fetch_ticker(pair)
        except Exception as exc:
            raise DataError(f"{self.exchange.id}: nepodařilo se načíst kotaci {pair}: {exc}") from exc
        price = ticker.get("last") or ticker.get("close")
        if price is None:
            raise DataError(f"{self.exchange.id}: žádná cena pro {pair}.")
        prev = ticker.get("previousClose") or ticker.get("open")
        return Quote(
            symbol=pair,
            price=float(price),
            previous_close=float(prev) if prev else None,
            day_high=float(ticker["high"]) if ticker.get("high") else None,
            day_low=float(ticker["low"]) if ticker.get("low") else None,
            currency=pair.split("/")[-1],
            timestamp=pd.Timestamp(ticker["timestamp"], unit="ms", tz="UTC").to_pydatetime()
            if ticker.get("timestamp")
            else None,
        )
