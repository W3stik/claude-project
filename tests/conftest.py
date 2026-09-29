from __future__ import annotations

from datetime import datetime, timezone

import numpy as np
import pandas as pd
import pytest

from daytrader.config import get_settings
from daytrader.data.synthetic import SyntheticProvider

# Friday 2026-09-25, 16:30 New York - after the close, so the whole week is available.
FRIDAY_AFTER_CLOSE = datetime(2026, 9, 25, 20, 30, tzinfo=timezone.utc)


class Clock:
    def __init__(self, now: datetime) -> None:
        self.now = now

    def __call__(self) -> datetime:
        return self.now


@pytest.fixture
def clock() -> Clock:
    return Clock(FRIDAY_AFTER_CLOSE)


@pytest.fixture
def demo(clock: Clock) -> SyntheticProvider:
    return SyntheticProvider(now=clock)


@pytest.fixture
def bars(demo: SyntheticProvider) -> pd.DataFrame:
    return demo.get_bars("AAPL", "5m", "10d")


@pytest.fixture(autouse=True)
def isolated_settings(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    """Never read the developer's .env or touch ~/.daytrader during tests."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("DT_DATA_DIR", str(tmp_path / "data"))
    for key in ("ALPACA_API_KEY", "ALPACA_SECRET_KEY", "ANTHROPIC_API_KEY", "CCXT_API_KEY", "CCXT_SECRET"):
        monkeypatch.delenv(key, raising=False)
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def make_bars(
    closes: list[float],
    start: str = "2026-09-21 09:30",
    freq: str = "5min",
    tz: str = "America/New_York",
    spread: float = 0.1,
    volume: float = 1000.0,
    opens: list[float] | None = None,
) -> pd.DataFrame:
    """Simple OHLCV frame: open = previous close unless given, high/low = +/- spread."""
    closes_arr = np.asarray(closes, dtype=float)
    opens_arr = np.asarray(opens, dtype=float) if opens is not None else np.r_[closes_arr[0], closes_arr[:-1]]
    index = pd.date_range(start, periods=len(closes_arr), freq=freq, tz=tz)
    return pd.DataFrame(
        {
            "open": opens_arr,
            "high": np.maximum(opens_arr, closes_arr) + spread,
            "low": np.minimum(opens_arr, closes_arr) - spread,
            "close": closes_arr,
            "volume": volume,
        },
        index=index,
    )


def make_session_bars(days: list[list[float]], start_day: str = "2026-09-21", **kwargs) -> pd.DataFrame:
    """Several sessions of 5-minute bars starting 09:30 each (business days)."""
    frames = []
    for offset, closes in zip(pd.bdate_range(start_day, periods=len(days)), days):
        frames.append(make_bars(closes, start=f"{offset.date()} 09:30", **kwargs))
    return pd.concat(frames)
