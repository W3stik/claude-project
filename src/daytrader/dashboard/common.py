"""Shared dashboard helpers: cached resources, sidebar, formatting and error handling."""

from __future__ import annotations

import threading
from collections import deque
from collections.abc import Callable
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any

import pandas as pd
import streamlit as st

from .. import DISCLAIMER
from ..ai import AIError
from ..bot import Decision, TradingBot
from ..brokers import BROKERS, Broker, BrokerError, create_broker
from ..config import ConfigError, Settings, get_settings
from ..data import PROVIDERS, DataError, DataProvider, create_provider
from ..journal import Journal
from ..models import NewsItem

KNOWN_ERRORS = (ConfigError, DataError, BrokerError, AIError, ValueError)


def settings() -> Settings:
    return get_settings()


@st.cache_resource(show_spinner=False)
def get_provider(name: str) -> DataProvider:
    return create_provider(name, settings())


@st.cache_resource(show_spinner=False)
def get_broker(name: str, provider_name: str) -> Broker:
    return create_broker(name, settings(), provider=get_provider(provider_name))


@st.cache_resource(show_spinner=False)
def get_journal() -> Journal:
    return Journal(settings().ensure_data_dir() / "journal.db")


@st.cache_data(ttl=60, show_spinner="Načítám data…")
def load_bars(provider_name: str, symbol: str, interval: str, period: str) -> pd.DataFrame:
    return get_provider(provider_name).get_bars(symbol, interval=interval, period=period)


@st.cache_data(ttl=600, show_spinner=False)
def load_news(provider_name: str, symbol: str) -> list[NewsItem]:
    provider = get_provider(provider_name)
    return provider.get_news(symbol, 8) if provider.supports_news else []


def theme_mode() -> str:
    try:
        mode = st.context.theme.type
    except Exception:
        mode = None
    return mode if mode in ("light", "dark") else "light"


def provider_name() -> str:
    return st.session_state.get("provider_name", settings().data_provider)


def broker_name() -> str:
    return st.session_state.get("broker_name", settings().broker)


def render_sidebar() -> None:
    cfg = settings()
    with st.sidebar:
        providers = list(PROVIDERS)
        default_provider = cfg.data_provider if cfg.data_provider in providers else "yahoo"
        st.selectbox(
            "Zdroj dat",
            providers,
            index=providers.index(st.session_state.get("provider_name", default_provider)),
            format_func=lambda key: PROVIDERS[key],
            key="provider_name",
            help="Odkud se berou ceny pro grafy, scanner, backtest i papírový účet.",
        )
        brokers = list(BROKERS)
        default_broker = cfg.broker if cfg.broker in brokers else "paper"
        st.selectbox(
            "Broker",
            brokers,
            index=brokers.index(st.session_state.get("broker_name", default_broker)),
            format_func=lambda key: BROKERS[key],
            key="broker_name",
            help="Kam se posílají příkazy. Papírový účet je lokální simulace bez rizika.",
        )
        if cfg.live_trading:
            st.error("Živé obchodování je POVOLENO (DT_LIVE_TRADING=true).", icon="⚠️")
        st.caption(DISCLAIMER)


@contextmanager
def guard():
    """Show known errors as friendly messages instead of tracebacks."""
    try:
        yield
    except KNOWN_ERRORS as exc:
        st.error(str(exc))
        st.stop()


def fmt(value: Any, digits: int = 2, suffix: str = "") -> str:
    if value is None:
        return "—"
    try:
        number = float(value)
    except (TypeError, ValueError):
        return str(value)
    if pd.isna(number):
        return "—"
    return f"{number:,.{digits}f}".replace(",", " ") + suffix


def polarity(value: float | None) -> str:
    """Delta colour for st.metric: blue = up/profit, orange = down/loss (same as the charts)."""
    if value is None or pd.isna(value) or value == 0:
        return "gray"
    return "blue" if value > 0 else "orange"


def viewer_tz() -> str:
    """The viewer's timezone as reported by the browser (fallback: Prague)."""
    try:
        return st.context.timezone or "Europe/Prague"
    except Exception:
        return "Europe/Prague"


def local_time(values: pd.Series) -> pd.Series:
    """UTC timestamps -> the viewer's timezone for display."""
    stamps = pd.to_datetime(values, utc=True)
    return stamps.dt.tz_convert(viewer_tz()).dt.tz_localize(None)


def local_dt(value: datetime) -> datetime:
    stamp = pd.Timestamp(value)
    stamp = stamp.tz_localize("UTC") if stamp.tzinfo is None else stamp
    return stamp.tz_convert(viewer_tz()).to_pydatetime()


# -- background bot ---------------------------------------------------------------------
class BotRunner:
    """Keeps one trading bot thread alive across Streamlit reruns."""

    def __init__(self) -> None:
        self.thread: threading.Thread | None = None
        self.stop_event: threading.Event | None = None
        self.bot: TradingBot | None = None
        self.label = ""
        self.started_at: datetime | None = None
        self.decisions: deque[tuple[datetime, Decision]] = deque(maxlen=300)
        self.last_error: str | None = None

    @property
    def running(self) -> bool:
        return self.thread is not None and self.thread.is_alive()

    def start(self, bot: TradingBot, label: str, on_stop: Callable[[], None] | None = None) -> None:
        if self.running:
            raise BrokerError("Bot už běží – nejdřív ho zastav.")
        self.stop_event = threading.Event()
        self.bot = bot
        self.label = label
        self.started_at = datetime.now(timezone.utc)
        self.last_error = None

        def record(decisions: list[Decision]) -> None:
            now = datetime.now(timezone.utc)
            for decision in decisions:
                if decision.action not in ("hold", "skip"):
                    self.decisions.appendleft((now, decision))

        def target() -> None:
            try:
                bot.run_forever(self.stop_event, on_decisions=record)
            except Exception as exc:  # pragma: no cover - defensive
                self.last_error = str(exc)
            finally:
                if on_stop:
                    on_stop()

        self.thread = threading.Thread(target=target, name="daytrader-bot", daemon=True)
        self.thread.start()

    def stop(self) -> None:
        if self.stop_event is not None:
            self.stop_event.set()
        if self.thread is not None:
            self.thread.join(timeout=10)


@st.cache_resource(show_spinner=False)
def bot_runner() -> BotRunner:
    return BotRunner()
