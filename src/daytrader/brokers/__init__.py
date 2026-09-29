from __future__ import annotations

from ..config import ConfigError, Settings, get_settings
from ..data import DataProvider, create_provider
from .base import Broker, BrokerError
from .paper import PaperBroker

BROKERS: dict[str, str] = {
    "paper": "Papírový účet (lokální simulace)",
    "alpaca": "Alpaca (paper nebo live)",
    "ccxt": "Kryptoburza přes CCXT (testnet nebo live)",
}

LIVE_BLOCKED = (
    "Živé obchodování se skutečnými penězi je zablokované. Pokud ho opravdu chceš, "
    "nastav v .env DT_LIVE_TRADING=true (a počítej s tím, že můžeš přijít o peníze)."
)


def paper_db_path(settings: Settings, provider: DataProvider) -> str:
    """One paper account per price source, so demo prices never mix with real ones."""
    return str(settings.ensure_data_dir() / f"paper-{provider.name}.db")


def create_broker(
    name: str | None = None,
    settings: Settings | None = None,
    provider: DataProvider | None = None,
) -> Broker:
    settings = settings or get_settings()
    name = (name or settings.broker).strip().lower()
    if name == "paper":
        provider = provider or create_provider(settings=settings)
        return PaperBroker(
            paper_db_path(settings, provider),
            provider,
            starting_cash=settings.paper_starting_cash,
            commission_per_share=settings.paper_commission_per_share,
            commission_pct=settings.paper_commission_pct,
            min_commission=settings.paper_min_commission,
            slippage_bps=settings.paper_slippage_bps,
            allow_short=settings.allow_short,
        )
    if name == "alpaca":
        if not settings.has_alpaca:
            raise ConfigError("Pro Alpaca vyplň ALPACA_API_KEY a ALPACA_SECRET_KEY v souboru .env.")
        if not settings.alpaca_paper and not settings.live_trading:
            raise ConfigError(LIVE_BLOCKED)
        from .alpaca import AlpacaBroker

        return AlpacaBroker(
            settings.alpaca_api_key.get_secret_value(),
            settings.alpaca_secret_key.get_secret_value(),
            paper=settings.alpaca_paper,
        )
    if name == "ccxt":
        if not (settings.ccxt_api_key and settings.ccxt_secret):
            raise ConfigError("Pro obchodování na burze vyplň CCXT_API_KEY a CCXT_SECRET v souboru .env.")
        if not settings.ccxt_sandbox and not settings.live_trading:
            raise ConfigError(LIVE_BLOCKED)
        from ..data.ccxt_provider import create_exchange
        from .ccxt_broker import CCXTBroker

        exchange = create_exchange(
            settings.ccxt_exchange,
            settings.ccxt_api_key.get_secret_value(),
            settings.ccxt_secret.get_secret_value(),
            settings.ccxt_password.get_secret_value() if settings.ccxt_password else None,
            sandbox=settings.ccxt_sandbox,
        )
        return CCXTBroker(
            exchange,
            quote_currency=settings.ccxt_quote_currency,
            sandbox=settings.ccxt_sandbox,
            symbols=settings.watchlist_symbols,
        )
    raise ConfigError(f"Neznámý broker '{name}'. Možnosti: {', '.join(BROKERS)}.")


__all__ = ["BROKERS", "Broker", "BrokerError", "PaperBroker", "create_broker", "paper_db_path"]
