"""Trading-session calendars (regular hours only, no holiday calendar).

Holidays are not modelled; the bot additionally skips symbols whose latest bar is
stale, which covers exchange holidays in practice.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

import pandas as pd


@dataclass(frozen=True)
class MarketSession:
    key: str
    label: str
    tz: str
    open: time | None = None  # None = trades around the clock
    close: time | None = None
    weekdays_only: bool = True

    @property
    def is_24h(self) -> bool:
        return self.open is None or self.close is None

    @property
    def zone(self) -> ZoneInfo:
        return ZoneInfo(self.tz)

    def local(self, now: datetime) -> datetime:
        if now.tzinfo is None:
            now = now.replace(tzinfo=timezone.utc)
        return now.astimezone(self.zone)

    def is_open(self, now: datetime) -> bool:
        local = self.local(now)
        if self.weekdays_only and local.weekday() >= 5:
            return False
        if self.is_24h:
            return True
        return self.open <= local.time() < self.close

    def minutes_to_close(self, now: datetime) -> float | None:
        """Minutes until today's close, ``None`` for 24h markets or when closed."""
        if self.is_24h or not self.is_open(now):
            return None
        local = self.local(now)
        close_dt = local.replace(
            hour=self.close.hour, minute=self.close.minute, second=0, microsecond=0
        )
        return (close_dt - local).total_seconds() / 60

    def next_open(self, now: datetime) -> datetime | None:
        """Next regular session open after ``now`` (exchange time); ``None`` for 24h markets."""
        if self.is_24h:
            return None
        local = self.local(now)
        day = local.date()
        for _ in range(8):
            candidate = datetime.combine(day, self.open, tzinfo=self.zone)
            if candidate > local and not (self.weekdays_only and candidate.weekday() >= 5):
                return candidate
            day += timedelta(days=1)
        return None

    def minutes_since_open(self, now: datetime) -> float | None:
        if self.is_24h or not self.is_open(now):
            return None
        local = self.local(now)
        open_dt = local.replace(hour=self.open.hour, minute=self.open.minute, second=0, microsecond=0)
        return (local - open_dt).total_seconds() / 60


SESSIONS: dict[str, MarketSession] = {
    "us": MarketSession("us", "USA (NYSE/Nasdaq)", "America/New_York", time(9, 30), time(16, 0)),
    "prague": MarketSession("prague", "Burza cenných papírů Praha", "Europe/Prague", time(9, 0), time(16, 20)),
    "xetra": MarketSession("xetra", "Xetra (Frankfurt)", "Europe/Berlin", time(9, 0), time(17, 30)),
    "london": MarketSession("london", "London Stock Exchange", "Europe/London", time(8, 0), time(16, 30)),
    "crypto": MarketSession("crypto", "Krypto (24/7)", "UTC", None, None, weekdays_only=False),
}

_SUFFIX_SESSIONS = {".PR": "prague", ".DE": "xetra", ".F": "xetra", ".L": "london"}
_CRYPTO_QUOTES = ("USDT", "USDC", "BUSD", "USD", "EUR", "BTC", "ETH")


def is_crypto_symbol(symbol: str) -> bool:
    s = symbol.upper()
    if "/" in s:
        return True
    # Yahoo style crypto tickers, e.g. BTC-USD, ETH-EUR
    if "-" in s and s.rsplit("-", 1)[1] in _CRYPTO_QUOTES:
        return True
    return False


def session_for_symbol(symbol: str) -> MarketSession:
    """Best-effort guess of the exchange session from the ticker format."""
    if is_crypto_symbol(symbol):
        return SESSIONS["crypto"]
    upper = symbol.upper()
    for suffix, key in _SUFFIX_SESSIONS.items():
        if upper.endswith(suffix):
            return SESSIONS[key]
    return SESSIONS["us"]


def filter_regular_hours(bars: pd.DataFrame, session: MarketSession) -> pd.DataFrame:
    """Keep only bars that start inside the regular session (drops pre/after-market)."""
    if session.is_24h or bars.empty:
        return bars
    local = bars.index.tz_convert(session.tz)
    times = local.time
    mask = (times >= session.open) & (times < session.close)
    if session.weekdays_only:
        mask &= local.weekday < 5
    return bars[mask]
