"""Application settings loaded from environment variables and an optional ``.env`` file."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import AliasChoices, Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class ConfigError(RuntimeError):
    """Raised when the configuration does not allow the requested action."""


def _alias(*names: str) -> AliasChoices:
    return AliasChoices(*names)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="DT_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        validate_by_name=True,
        validate_by_alias=True,
    )

    # --- general -----------------------------------------------------------
    data_provider: str = "yahoo"
    broker: str = "paper"
    data_dir: Path = Path.home() / ".daytrader"
    watchlist: str = "AAPL,MSFT,NVDA,TSLA,AMD,META,AMZN,SPY,QQQ"
    live_trading: bool = False

    # --- paper account -----------------------------------------------------
    paper_starting_cash: float = 10_000.0
    paper_commission_per_share: float = 0.0
    paper_commission_pct: float = 0.0
    paper_min_commission: float = 0.0
    paper_slippage_bps: float = 2.0

    # --- risk management ---------------------------------------------------
    risk_per_trade_pct: float = 1.0
    max_position_pct: float = 25.0
    max_daily_loss_pct: float = 3.0
    max_open_positions: int = 3
    max_trades_per_day: int = 10
    stop_atr_mult: float = 1.5
    take_profit_r: float = 2.0
    allow_short: bool = False

    # --- automatic bot (daytrader bot / bot.bat) ----------------------------
    bot_strategy: str = "vwap_trend"
    bot_interval: str = "5m"
    bot_symbols: str = ""  # empty = DT_WATCHLIST
    bot_params: str = ""  # e.g. "fast=9,slow=21"

    # --- Alpaca --------------------------------------------------------------
    alpaca_api_key: SecretStr | None = Field(None, validation_alias=_alias("ALPACA_API_KEY", "alpaca_api_key"))
    alpaca_secret_key: SecretStr | None = Field(
        None, validation_alias=_alias("ALPACA_SECRET_KEY", "alpaca_secret_key")
    )
    alpaca_paper: bool = Field(True, validation_alias=_alias("ALPACA_PAPER", "alpaca_paper"))
    alpaca_data_feed: str = Field("iex", validation_alias=_alias("ALPACA_DATA_FEED", "alpaca_data_feed"))

    # --- CCXT (crypto exchanges) -------------------------------------------
    ccxt_exchange: str = Field("binance", validation_alias=_alias("CCXT_EXCHANGE", "ccxt_exchange"))
    ccxt_api_key: SecretStr | None = Field(None, validation_alias=_alias("CCXT_API_KEY", "ccxt_api_key"))
    ccxt_secret: SecretStr | None = Field(None, validation_alias=_alias("CCXT_SECRET", "ccxt_secret"))
    ccxt_password: SecretStr | None = Field(None, validation_alias=_alias("CCXT_PASSWORD", "ccxt_password"))
    ccxt_sandbox: bool = Field(True, validation_alias=_alias("CCXT_SANDBOX", "ccxt_sandbox"))
    ccxt_quote_currency: str = Field(
        "USDT", validation_alias=_alias("CCXT_QUOTE_CURRENCY", "ccxt_quote_currency")
    )

    # --- AI analyst (Claude API) ---------------------------------------------
    anthropic_api_key: SecretStr | None = Field(
        None, validation_alias=_alias("ANTHROPIC_API_KEY", "anthropic_api_key")
    )
    ai_model: str = "claude-opus-5-5"
    ai_effort: str = "medium"

    @field_validator(
        "alpaca_api_key",
        "alpaca_secret_key",
        "ccxt_api_key",
        "ccxt_secret",
        "ccxt_password",
        "anthropic_api_key",
        mode="before",
    )
    @classmethod
    def _empty_secret_is_none(cls, value: object) -> object:
        if isinstance(value, str) and not value.strip():
            return None
        return value

    @field_validator("data_provider", "broker", "ccxt_exchange", "ai_effort", "bot_strategy", mode="before")
    @classmethod
    def _lower(cls, value: object) -> object:
        return value.strip().lower() if isinstance(value, str) else value

    @property
    def watchlist_symbols(self) -> list[str]:
        return parse_symbols(self.watchlist)

    @property
    def bot_symbol_list(self) -> list[str]:
        return parse_symbols(self.bot_symbols) or self.watchlist_symbols

    @property
    def bot_param_dict(self) -> dict[str, str]:
        params: dict[str, str] = {}
        for part in self.bot_params.replace(";", ",").split(","):
            if "=" in part:
                key, value = part.split("=", 1)
                params[key.strip()] = value.strip()
        return params

    @property
    def has_alpaca(self) -> bool:
        return bool(self.alpaca_api_key and self.alpaca_secret_key)

    @property
    def has_ai(self) -> bool:
        return self.anthropic_api_key is not None

    def ensure_data_dir(self) -> Path:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        return self.data_dir

    def masked_summary(self) -> dict[str, str]:
        """Human readable configuration overview without secrets."""

        def mask(secret: SecretStr | None) -> str:
            if secret is None:
                return "—"
            value = secret.get_secret_value()
            return f"…{value[-4:]}" if len(value) > 4 else "****"

        return {
            "Zdroj dat": self.data_provider,
            "Broker": self.broker,
            "Živé obchodování povoleno": "ANO" if self.live_trading else "ne",
            "Složka s daty": str(self.data_dir),
            "Watchlist": ", ".join(self.watchlist_symbols),
            "Riziko na obchod": f"{self.risk_per_trade_pct} %",
            "Max. denní ztráta": f"{self.max_daily_loss_pct} %",
            "Max. pozice": f"{self.max_position_pct} % kapitálu",
            "Max. otevřených pozic": str(self.max_open_positions),
            "Shortování": "povoleno" if self.allow_short else "zakázáno",
            "Bot": f"{self.bot_strategy} · {self.bot_interval} · {', '.join(self.bot_symbol_list)}",
            "Alpaca klíč": mask(self.alpaca_api_key),
            "Alpaca režim": "paper" if self.alpaca_paper else "LIVE",
            "CCXT burza": f"{self.ccxt_exchange} ({'testnet' if self.ccxt_sandbox else 'LIVE'})",
            "CCXT klíč": mask(self.ccxt_api_key),
            "Anthropic klíč": mask(self.anthropic_api_key),
            "AI model": self.ai_model,
        }


def parse_symbols(text: str | None) -> list[str]:
    if not text:
        return []
    seen: dict[str, None] = {}
    for part in text.replace(";", ",").replace("\n", ",").split(","):
        symbol = part.strip().upper()
        if symbol:
            seen.setdefault(symbol, None)
    return list(seen)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
