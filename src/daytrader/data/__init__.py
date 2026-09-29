from __future__ import annotations

from ..config import ConfigError, Settings, get_settings
from .base import DataError, DataProvider, drop_incomplete_bar, normalize_bars
from .synthetic import SyntheticProvider
from .yahoo import YahooProvider

PROVIDERS: dict[str, str] = {
    "yahoo": "Yahoo Finance (zdarma, bez klíče)",
    "alpaca": "Alpaca (US akcie + krypto, klíč zdarma)",
    "ccxt": "Kryptoburza přes CCXT (veřejná data)",
    "demo": "Demo data (generovaná, offline)",
}


def create_provider(name: str | None = None, settings: Settings | None = None) -> DataProvider:
    settings = settings or get_settings()
    name = (name or settings.data_provider).strip().lower()
    if name == "yahoo":
        return YahooProvider()
    if name in ("demo", "synthetic"):
        return SyntheticProvider()
    if name == "alpaca":
        if not settings.has_alpaca:
            raise ConfigError("Pro Alpaca data vyplň ALPACA_API_KEY a ALPACA_SECRET_KEY v souboru .env.")
        from .alpaca import AlpacaDataProvider

        return AlpacaDataProvider(
            settings.alpaca_api_key.get_secret_value(),
            settings.alpaca_secret_key.get_secret_value(),
            feed=settings.alpaca_data_feed,
        )
    if name == "ccxt":
        from .ccxt_provider import CCXTDataProvider, create_exchange

        # Public market data from the real exchange (testnet prices are not representative).
        return CCXTDataProvider(create_exchange(settings.ccxt_exchange))
    raise ConfigError(f"Neznámý zdroj dat '{name}'. Možnosti: {', '.join(PROVIDERS)}.")


__all__ = [
    "PROVIDERS",
    "DataError",
    "DataProvider",
    "SyntheticProvider",
    "YahooProvider",
    "create_provider",
    "drop_incomplete_bar",
    "normalize_bars",
]
