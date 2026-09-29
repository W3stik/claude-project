"""Trading journal: bot/order log in SQLite plus round-trip trade statistics from fills."""

from __future__ import annotations

import sqlite3
from collections import deque
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from .backtest.metrics import trade_stats
from .models import Fill, Side

SCHEMA = """
CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT NOT NULL, level TEXT NOT NULL,
    source TEXT, symbol TEXT, message TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS orders (
    id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT NOT NULL, broker TEXT, order_id TEXT,
    symbol TEXT, side TEXT, qty REAL, type TEXT, price REAL, stop_loss REAL, take_profit REAL,
    strategy TEXT, reason TEXT, status TEXT
);
CREATE TABLE IF NOT EXISTS bot_state (
    symbol TEXT PRIMARY KEY, side TEXT, entry REAL, stop REAL, target REAL, updated TEXT
);
"""


def _now() -> datetime:
    return datetime.now(timezone.utc)


class Journal:
    def __init__(self, db_path: str | Path) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._tx() as conn:
            conn.executescript(SCHEMA)

    @contextmanager
    def _tx(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.db_path, timeout=30)
        conn.row_factory = sqlite3.Row
        try:
            with conn:
                yield conn
        finally:
            conn.close()

    # -- events ----------------------------------------------------------------------
    def log(self, message: str, level: str = "info", source: str = "app", symbol: str | None = None,
            ts: datetime | None = None) -> None:
        with self._tx() as conn:
            conn.execute(
                "INSERT INTO events (ts, level, source, symbol, message) VALUES (?, ?, ?, ?, ?)",
                ((ts or _now()).isoformat(), level, source, symbol, message),
            )

    def events(self, limit: int = 200) -> pd.DataFrame:
        with self._tx() as conn:
            rows = conn.execute("SELECT * FROM events ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
        return pd.DataFrame([dict(r) for r in rows], columns=["id", "ts", "level", "source", "symbol", "message"])

    # -- orders ----------------------------------------------------------------------
    def log_order(
        self,
        broker: str,
        symbol: str,
        side: str,
        qty: float,
        order_type: str,
        price: float | None,
        stop_loss: float | None = None,
        take_profit: float | None = None,
        strategy: str | None = None,
        reason: str | None = None,
        order_id: str | None = None,
        status: str | None = None,
        ts: datetime | None = None,
    ) -> None:
        with self._tx() as conn:
            conn.execute(
                """INSERT INTO orders (ts, broker, order_id, symbol, side, qty, type, price, stop_loss,
                   take_profit, strategy, reason, status) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                ((ts or _now()).isoformat(), broker, order_id, symbol, side, qty, order_type, price,
                 stop_loss, take_profit, strategy, reason, status),
            )

    def orders(self, limit: int = 200) -> pd.DataFrame:
        with self._tx() as conn:
            rows = conn.execute("SELECT * FROM orders ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
        return pd.DataFrame([dict(r) for r in rows])

    def entries_since(self, since: datetime, broker: str | None = None) -> int:
        """Number of entry orders logged since ``since`` (used for the max-trades-per-day rule)."""
        query = "SELECT COUNT(*) AS n FROM orders WHERE ts >= ? AND reason LIKE 'entry%'"
        params: list[Any] = [since.isoformat()]
        if broker:
            query += " AND broker = ?"
            params.append(broker)
        with self._tx() as conn:
            return int(conn.execute(query, params).fetchone()["n"])

    # -- bot state (client-side stops for brokers without bracket orders) ------------
    def set_state(self, symbol: str, side: str, entry: float, stop: float | None, target: float | None) -> None:
        with self._tx() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO bot_state (symbol, side, entry, stop, target, updated) VALUES (?, ?, ?, ?, ?, ?)",
                (symbol, side, entry, stop, target, _now().isoformat()),
            )

    def get_state(self, symbol: str) -> dict[str, Any] | None:
        with self._tx() as conn:
            row = conn.execute("SELECT * FROM bot_state WHERE symbol = ?", (symbol,)).fetchone()
        return dict(row) if row else None

    def clear_state(self, symbol: str) -> None:
        with self._tx() as conn:
            conn.execute("DELETE FROM bot_state WHERE symbol = ?", (symbol,))


# -- round trips & statistics ------------------------------------------------------------
ROUND_TRIP_COLUMNS = [
    "symbol", "side", "entry_time", "exit_time", "qty", "entry_price", "exit_price",
    "pnl", "pnl_pct", "commission",
]


def round_trips(fills: list[Fill]) -> pd.DataFrame:
    """Match fills FIFO per symbol into closed long/short round trips (partial fills supported)."""
    trips: list[dict[str, Any]] = []
    books: dict[str, deque] = {}
    for fill in sorted(fills, key=lambda f: f.timestamp):
        book = books.setdefault(fill.symbol, deque())
        signed = fill.qty if fill.side is Side.BUY else -fill.qty
        fee_per_unit = fill.commission / fill.qty if fill.qty else 0.0
        remaining = signed
        while book and remaining != 0 and np.sign(book[0]["qty"]) != np.sign(remaining):
            lot = book[0]
            take = min(abs(lot["qty"]), abs(remaining))
            direction = 1 if lot["qty"] > 0 else -1
            gross = (fill.price - lot["price"]) * take * direction
            fees = (lot["fee"] + fee_per_unit) * take
            trips.append(
                {
                    "symbol": fill.symbol,
                    "side": "long" if direction > 0 else "short",
                    "entry_time": lot["time"],
                    "exit_time": fill.timestamp,
                    "qty": take,
                    "entry_price": lot["price"],
                    "exit_price": fill.price,
                    "pnl": gross - fees,
                    "pnl_pct": (gross - fees) / (lot["price"] * take) * 100,
                    "commission": fees,
                }
            )
            lot["qty"] -= take * direction
            remaining += take * direction
            if abs(lot["qty"]) < 1e-12:
                book.popleft()
            if abs(remaining) < 1e-12:
                remaining = 0
        if remaining != 0:
            book.append({"qty": remaining, "price": fill.price, "time": fill.timestamp, "fee": fee_per_unit})
    return pd.DataFrame(trips, columns=ROUND_TRIP_COLUMNS)


def journal_stats(trips: pd.DataFrame) -> dict[str, Any]:
    return trade_stats(trips)


def daily_pnl(trips: pd.DataFrame, tz: str = "Europe/Prague") -> pd.Series:
    if trips.empty:
        return pd.Series(dtype=float, name="pnl")
    exit_times = pd.to_datetime(trips["exit_time"], utc=True).dt.tz_convert(tz)
    grouped = trips.groupby(exit_times.dt.date)["pnl"].sum()
    grouped.index.name = "date"
    return grouped.rename("pnl")
