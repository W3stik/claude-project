"""Minimal Alpaca REST helper shared by the Alpaca data provider and broker."""

from __future__ import annotations

from typing import Any

import httpx

from .timeframes import parse_interval

TRADING_URL_PAPER = "https://paper-api.alpaca.markets"
TRADING_URL_LIVE = "https://api.alpaca.markets"
DATA_URL = "https://data.alpaca.markets"


class AlpacaHTTP:
    def __init__(
        self,
        base_url: str,
        api_key: str,
        secret_key: str,
        client: httpx.Client | None = None,
        error_cls: type[Exception] = RuntimeError,
        timeout: float = 20.0,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.client = client or httpx.Client(timeout=timeout)
        self.error_cls = error_cls
        self.headers = {
            "APCA-API-KEY-ID": api_key,
            "APCA-API-SECRET-KEY": secret_key,
            "Accept": "application/json",
        }

    def request(
        self,
        method: str,
        path: str,
        params: dict[str, Any] | None = None,
        json: dict[str, Any] | None = None,
    ) -> Any:
        try:
            response = self.client.request(
                method, f"{self.base_url}{path}", params=params, json=json, headers=self.headers
            )
        except httpx.HTTPError as exc:
            raise self.error_cls(f"Alpaca: síťová chyba ({exc}).") from exc
        if response.status_code >= 400:
            try:
                message = response.json().get("message") or response.text
            except ValueError:
                message = response.text
            hint = ""
            if response.status_code in (401, 403) and "key" in str(message).lower():
                hint = " Zkontroluj ALPACA_API_KEY/ALPACA_SECRET_KEY a ALPACA_PAPER (paper klíče nefungují na live a naopak)."
            raise self.error_cls(f"Alpaca API {response.status_code}: {message}.{hint}")
        if not response.content:
            return None
        return response.json()


def alpaca_timeframe(interval: str) -> str:
    amount, unit = parse_interval(interval)
    if unit == "m":
        if amount > 59:
            return alpaca_timeframe(f"{amount // 60}h")
        return f"{amount}Min"
    if unit == "h":
        return f"{amount}Hour"
    return f"{amount}Day"


def alpaca_symbol(symbol: str) -> str:
    """Alpaca uses ``BTC/USD`` for crypto market data but ``BTCUSD`` in position paths."""
    return symbol.replace("/", "")


def rfc3339(ts: Any) -> str:
    import pandas as pd

    stamp = pd.Timestamp(ts)
    stamp = stamp.tz_localize("UTC") if stamp.tzinfo is None else stamp.tz_convert("UTC")
    return stamp.strftime("%Y-%m-%dT%H:%M:%SZ")
