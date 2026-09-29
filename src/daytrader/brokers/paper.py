"""Local paper-trading broker backed by SQLite.

Market orders fill immediately at the latest price plus slippage. Limit/stop orders and
the stop-loss/take-profit legs of bracket orders rest until :meth:`PaperBroker.sync`
replays 1-minute bars since the last check and fills whatever was touched (stops before
targets when both are hit in the same minute - the conservative assumption).
"""

from __future__ import annotations

import math
import sqlite3
import uuid
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd

from ..data.base import DataError, DataProvider, utcnow
from ..models import Account, Fill, Order, OrderRequest, OrderStatus, OrderType, Position, Side, TimeInForce
from ..sessions import is_crypto_symbol, session_for_symbol
from .base import Broker, BrokerError

SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE IF NOT EXISTS positions (
    symbol TEXT PRIMARY KEY, qty REAL NOT NULL, avg_price REAL NOT NULL, opened_at TEXT
);
CREATE TABLE IF NOT EXISTS orders (
    id TEXT PRIMARY KEY, client_order_id TEXT, symbol TEXT NOT NULL, side TEXT NOT NULL,
    qty REAL NOT NULL, type TEXT NOT NULL, limit_price REAL, stop_price REAL, tif TEXT,
    status TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT, filled_qty REAL DEFAULT 0,
    filled_avg_price REAL, filled_at TEXT, parent_id TEXT, oco_group TEXT,
    stop_loss REAL, take_profit REAL, last_checked TEXT, note TEXT
);
CREATE TABLE IF NOT EXISTS fills (
    id TEXT PRIMARY KEY, order_id TEXT, symbol TEXT NOT NULL, side TEXT NOT NULL,
    qty REAL NOT NULL, price REAL NOT NULL, commission REAL DEFAULT 0, ts TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_orders_status ON orders(status);
CREATE INDEX IF NOT EXISTS idx_fills_ts ON fills(ts);
"""

OPEN_STATUSES = (OrderStatus.NEW.value, OrderStatus.PARTIALLY_FILLED.value)


def trigger_price(
    order_type: OrderType, side: Side, limit: float | None, stop: float | None, o: float, h: float, low: float
) -> float | None:
    """Fill price of a resting order if the bar (open/high/low) touched it, else ``None``."""
    if order_type is OrderType.MARKET:  # queued while the market was closed -> fills at the open
        return o
    if order_type is OrderType.LIMIT and limit is not None:
        if side is Side.BUY and low <= limit:
            return min(o, limit)
        if side is Side.SELL and h >= limit:
            return max(o, limit)
    if order_type is OrderType.STOP and stop is not None:
        if side is Side.BUY and h >= stop:
            return max(o, stop)
        if side is Side.SELL and low <= stop:
            return min(o, stop)
    return None


def _iso(ts: datetime) -> str:
    return pd.Timestamp(ts).tz_convert("UTC").isoformat() if pd.Timestamp(ts).tzinfo else pd.Timestamp(ts).tz_localize("UTC").isoformat()


def _session_date(session, created: datetime):
    """Trading date an order belongs to: orders placed after the close count for the next day."""
    local = session.local(created)
    day = local.date()
    if not session.is_24h and local.time() >= session.close:
        day += timedelta(days=1)
    while session.weekdays_only and day.weekday() >= 5:
        day += timedelta(days=1)
    return day


def _ts(value: str | None) -> datetime | None:
    return pd.Timestamp(value).to_pydatetime() if value else None


class PaperBroker(Broker):
    name = "paper"
    is_live = False
    supports_bracket = True
    supports_short = True

    def __init__(
        self,
        db_path: str | Path,
        provider: DataProvider,
        starting_cash: float = 10_000.0,
        commission_per_share: float = 0.0,
        commission_pct: float = 0.0,
        min_commission: float = 0.0,
        slippage_bps: float = 2.0,
        allow_short: bool = True,
        fractional: bool = False,
        clock: Callable[[], datetime] = utcnow,
    ) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.provider = provider
        self.starting_cash = starting_cash
        self.commission_per_share = commission_per_share
        self.commission_pct = commission_pct
        self.min_commission = min_commission
        self.slippage = slippage_bps / 10_000
        self.allow_short = allow_short
        self.fractional = fractional
        self.clock = clock
        self._prices: dict[str, float] = {}
        with self._tx() as conn:
            conn.executescript(SCHEMA)
            if self._meta(conn, "cash") is None:
                self._set_meta(conn, "cash", starting_cash)
                self._set_meta(conn, "starting_cash", starting_cash)
                self._set_meta(conn, "created_at", _iso(self.clock()))

    # -- storage helpers ---------------------------------------------------------
    @contextmanager
    def _tx(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.db_path, timeout=30)
        conn.row_factory = sqlite3.Row
        try:
            with conn:
                yield conn
        finally:
            conn.close()

    @staticmethod
    def _meta(conn: sqlite3.Connection, key: str) -> str | None:
        row = conn.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
        return row["value"] if row else None

    @staticmethod
    def _set_meta(conn: sqlite3.Connection, key: str, value: object) -> None:
        conn.execute("INSERT OR REPLACE INTO meta (key, value) VALUES (?, ?)", (key, str(value)))

    def _price(self, symbol: str) -> float | None:
        try:
            price = self.provider.get_latest_price(symbol)
        except DataError:
            return self._prices.get(symbol)
        self._prices[symbol] = price
        return price

    def _commission(self, qty: float, price: float) -> float:
        fee = qty * self.commission_per_share + qty * price * self.commission_pct / 100
        return max(fee, self.min_commission) if fee > 0 or self.min_commission > 0 else 0.0

    def _allows_fractional(self, symbol: str) -> bool:
        return self.fractional or is_crypto_symbol(symbol)

    # -- account -----------------------------------------------------------------
    def get_positions(self) -> list[Position]:
        with self._tx() as conn:
            rows = conn.execute("SELECT * FROM positions ORDER BY symbol").fetchall()
        return [
            Position(row["symbol"], row["qty"], row["avg_price"], self._price(row["symbol"])) for row in rows
        ]

    def get_account(self) -> Account:
        positions = self.get_positions()
        with self._tx() as conn:
            cash = float(self._meta(conn, "cash"))
            equity = cash + sum(p.qty * (p.current_price or p.avg_price) for p in positions)
            gross = sum(abs(p.qty) * (p.current_price or p.avg_price) for p in positions)
            today = pd.Timestamp(self.clock()).tz_convert("UTC").date().isoformat()
            if self._meta(conn, "day_start_date") != today:
                self._set_meta(conn, "day_start_date", today)
                self._set_meta(conn, "day_start_equity", equity)
            day_start = float(self._meta(conn, "day_start_equity"))
            starting = float(self._meta(conn, "starting_cash") or self.starting_cash)
        return Account(
            equity=equity,
            cash=cash,
            buying_power=max(0.0, equity - gross),
            currency="USD",
            day_start_equity=day_start,
            is_live=False,
            extra={"starting_cash": starting},
        )

    def reset(self, starting_cash: float | None = None) -> None:
        cash = starting_cash if starting_cash is not None else self.starting_cash
        with self._tx() as conn:
            for table in ("positions", "orders", "fills", "meta"):
                conn.execute(f"DELETE FROM {table}")
            self._set_meta(conn, "cash", cash)
            self._set_meta(conn, "starting_cash", cash)
            self._set_meta(conn, "created_at", _iso(self.clock()))

    # -- orders --------------------------------------------------------------------
    def submit_order(self, request: OrderRequest) -> Order:
        try:
            request.validate()
        except ValueError as exc:
            raise BrokerError(str(exc)) from exc
        symbol = request.symbol.upper()
        qty = float(request.qty)
        if not self._allows_fractional(symbol) and not float(qty).is_integer():
            raise BrokerError("Papírový účet obchoduje akcie jen v celých kusech.")
        now = self.clock()
        order_id = uuid.uuid4().hex[:12]
        price = self._price(symbol)
        if price is None:
            raise BrokerError(f"Nelze zjistit aktuální cenu {symbol} – příkaz nebyl přijat.")
        tif = TimeInForce.GTC if is_crypto_symbol(symbol) else request.time_in_force
        with self._tx() as conn:
            self._check_exposure(conn, symbol, request.side, qty, price)
            conn.execute(
                """INSERT INTO orders (id, client_order_id, symbol, side, qty, type, limit_price, stop_price, tif,
                   status, created_at, updated_at, stop_loss, take_profit, last_checked)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    order_id,
                    request.client_order_id,
                    symbol,
                    request.side.value,
                    qty,
                    request.type.value,
                    request.limit_price,
                    request.stop_price,
                    tif.value,
                    OrderStatus.NEW.value,
                    _iso(now),
                    _iso(now),
                    request.stop_loss,
                    request.take_profit,
                    _iso(now),
                ),
            )
            row = conn.execute("SELECT * FROM orders WHERE id = ?", (order_id,)).fetchone()
            if request.type is OrderType.MARKET:
                if session_for_symbol(symbol).is_open(now):
                    self._fill(conn, row, price * (1 + self.slippage * request.side.sign), now)
                else:
                    conn.execute(
                        "UPDATE orders SET note = ? WHERE id = ?",
                        ("Trh je zavřený – příkaz se vyplní při otevření.", order_id),
                    )
            else:
                fill = trigger_price(request.type, request.side, request.limit_price, request.stop_price, price, price, price)
                if fill is not None:
                    if request.type is OrderType.STOP:
                        fill *= 1 + self.slippage * request.side.sign
                    self._fill(conn, row, fill, now)
            return self._order_from_row(conn.execute("SELECT * FROM orders WHERE id = ?", (order_id,)).fetchone())

    def _check_exposure(self, conn: sqlite3.Connection, symbol: str, side: Side, qty: float, price: float) -> None:
        row = conn.execute("SELECT qty FROM positions WHERE symbol = ?", (symbol,)).fetchone()
        current = row["qty"] if row else 0.0
        new_qty = current + side.sign * qty
        if abs(new_qty) <= abs(current) + 1e-12 and math.copysign(1, new_qty or current) == math.copysign(1, current or new_qty):
            return  # reduces an existing position - always allowed
        if new_qty < 0 and not self.allow_short:
            raise BrokerError("Shortování je vypnuté (DT_ALLOW_SHORT=false) – nelze prodat víc, než držíš.")
        cash = float(self._meta(conn, "cash"))
        others = conn.execute("SELECT symbol, qty, avg_price FROM positions WHERE symbol != ?", (symbol,)).fetchall()
        other_value = sum(r["qty"] * self._prices.get(r["symbol"], r["avg_price"]) for r in others)
        other_gross = sum(abs(r["qty"]) * self._prices.get(r["symbol"], r["avg_price"]) for r in others)
        equity = cash + other_value + current * price
        if other_gross + abs(new_qty) * price > equity * 1.0001:
            raise BrokerError(
                f"Nedostatečná kupní síla: pozice {abs(new_qty) * price:,.0f} při kapitálu {equity:,.0f}."
            )

    def _fill(self, conn: sqlite3.Connection, row: sqlite3.Row, price: float, ts: datetime) -> None:
        side = Side(row["side"])
        qty = float(row["qty"])
        fee = self._commission(qty, price)
        symbol = row["symbol"]
        pos = conn.execute("SELECT * FROM positions WHERE symbol = ?", (symbol,)).fetchone()
        old_qty = pos["qty"] if pos else 0.0
        avg = pos["avg_price"] if pos else 0.0
        signed = side.sign * qty
        new_qty = old_qty + signed
        if abs(new_qty) < 1e-9:
            conn.execute("DELETE FROM positions WHERE symbol = ?", (symbol,))
        else:
            if old_qty == 0 or math.copysign(1, old_qty) == math.copysign(1, signed):
                avg = (abs(old_qty) * avg + qty * price) / abs(new_qty)
            elif abs(signed) > abs(old_qty):  # position flipped
                avg = price
            conn.execute(
                "INSERT OR REPLACE INTO positions (symbol, qty, avg_price, opened_at) VALUES (?, ?, ?, ?)",
                (symbol, new_qty, avg, pos["opened_at"] if pos and old_qty * new_qty > 0 else _iso(ts)),
            )
        cash = float(self._meta(conn, "cash")) - signed * price - fee
        self._set_meta(conn, "cash", cash)
        conn.execute(
            "INSERT INTO fills (id, order_id, symbol, side, qty, price, commission, ts) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (uuid.uuid4().hex[:12], row["id"], symbol, side.value, qty, price, fee, _iso(ts)),
        )
        conn.execute(
            """UPDATE orders SET status = ?, filled_qty = ?, filled_avg_price = ?, filled_at = ?, updated_at = ?
               WHERE id = ?""",
            (OrderStatus.FILLED.value, qty, price, _iso(ts), _iso(ts), row["id"]),
        )
        if row["oco_group"]:
            conn.execute(
                f"""UPDATE orders SET status = ?, updated_at = ? WHERE oco_group = ? AND id != ?
                    AND status IN ({','.join('?' * len(OPEN_STATUSES))})""",
                (OrderStatus.CANCELED.value, _iso(ts), row["oco_group"], row["id"], *OPEN_STATUSES),
            )
        if row["stop_loss"] is not None or row["take_profit"] is not None:
            exit_side = side.opposite().value
            legs = []
            if row["stop_loss"] is not None:
                legs.append((OrderType.STOP.value, None, row["stop_loss"]))
            if row["take_profit"] is not None:
                legs.append((OrderType.LIMIT.value, row["take_profit"], None))
            for order_type, limit, stop in legs:
                conn.execute(
                    """INSERT INTO orders (id, symbol, side, qty, type, limit_price, stop_price, tif, status,
                       created_at, updated_at, parent_id, oco_group, last_checked)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        uuid.uuid4().hex[:12],
                        symbol,
                        exit_side,
                        qty,
                        order_type,
                        limit,
                        stop,
                        TimeInForce.GTC.value,
                        OrderStatus.NEW.value,
                        _iso(ts),
                        _iso(ts),
                        row["id"],
                        row["id"],
                        _iso(ts),
                    ),
                )

    def cancel_order(self, order_id: str, symbol: str | None = None) -> None:
        with self._tx() as conn:
            row = conn.execute("SELECT status FROM orders WHERE id = ?", (order_id,)).fetchone()
            if row is None:
                raise BrokerError(f"Příkaz {order_id} neexistuje.")
            if row["status"] not in OPEN_STATUSES:
                raise BrokerError(f"Příkaz {order_id} už není aktivní ({row['status']}).")
            conn.execute(
                "UPDATE orders SET status = ?, updated_at = ? WHERE id = ?",
                (OrderStatus.CANCELED.value, _iso(self.clock()), order_id),
            )

    def get_orders(self, status: str = "open", limit: int = 100) -> list[Order]:
        query = "SELECT * FROM orders"
        params: tuple = ()
        if status == "open":
            query += f" WHERE status IN ({','.join('?' * len(OPEN_STATUSES))})"
            params = OPEN_STATUSES
        elif status == "closed":
            query += f" WHERE status NOT IN ({','.join('?' * len(OPEN_STATUSES))})"
            params = OPEN_STATUSES
        query += " ORDER BY created_at DESC LIMIT ?"
        with self._tx() as conn:
            rows = conn.execute(query, (*params, limit)).fetchall()
        return [self._order_from_row(row) for row in rows]

    def get_fills(self, since: datetime | None = None) -> list[Fill]:
        with self._tx() as conn:
            if since is not None:
                rows = conn.execute("SELECT * FROM fills WHERE ts >= ? ORDER BY ts", (_iso(since),)).fetchall()
            else:
                rows = conn.execute("SELECT * FROM fills ORDER BY ts").fetchall()
        return [
            Fill(
                id=row["id"],
                order_id=row["order_id"],
                symbol=row["symbol"],
                side=Side(row["side"]),
                qty=row["qty"],
                price=row["price"],
                timestamp=_ts(row["ts"]),
                commission=row["commission"] or 0.0,
            )
            for row in rows
        ]

    @staticmethod
    def _order_from_row(row: sqlite3.Row) -> Order:
        return Order(
            id=row["id"],
            symbol=row["symbol"],
            side=Side(row["side"]),
            qty=row["qty"],
            type=OrderType(row["type"]),
            status=OrderStatus(row["status"]),
            limit_price=row["limit_price"],
            stop_price=row["stop_price"],
            filled_qty=row["filled_qty"] or 0.0,
            filled_avg_price=row["filled_avg_price"],
            created_at=_ts(row["created_at"]),
            filled_at=_ts(row["filled_at"]),
            client_order_id=row["client_order_id"],
            parent_id=row["parent_id"],
            time_in_force=row["tif"] or "day",
        )

    # -- simulation ------------------------------------------------------------------
    def sync(self) -> None:
        """Fill resting orders that were touched since the last check; expire DAY orders."""
        now = pd.Timestamp(self.clock()).tz_convert("UTC")
        with self._tx() as conn:
            rows = conn.execute(
                f"SELECT * FROM orders WHERE status IN ({','.join('?' * len(OPEN_STATUSES))})",
                OPEN_STATUSES,
            ).fetchall()
            for row in rows:
                if row["tif"] == TimeInForce.DAY.value and row["type"] != OrderType.MARKET.value:
                    session = session_for_symbol(row["symbol"])
                    created = _session_date(session, pd.Timestamp(row["created_at"]).to_pydatetime())
                    if created < session.local(now.to_pydatetime()).date():
                        conn.execute(
                            "UPDATE orders SET status = ?, updated_at = ? WHERE id = ?",
                            (OrderStatus.EXPIRED.value, _iso(now), row["id"]),
                        )
        symbols = sorted({row["symbol"] for row in rows})
        for symbol in symbols:
            self._sync_symbol(symbol, now)

    def _sync_symbol(self, symbol: str, now: pd.Timestamp) -> None:
        with self._tx() as conn:
            rows = conn.execute(
                f"SELECT * FROM orders WHERE symbol = ? AND status IN ({','.join('?' * len(OPEN_STATUSES))})",
                (symbol, *OPEN_STATUSES),
            ).fetchall()
        if not rows:
            return
        since = min(pd.Timestamp(r["last_checked"] or r["created_at"]) for r in rows).floor("min")
        bars = None
        try:
            bars = self.provider.get_bars(symbol, interval="1m", start=since, end=now + pd.Timedelta(minutes=1))
            bars = bars[bars.index >= since]
        except (DataError, ValueError):
            bars = None
        if bars is None or bars.empty:
            price = self._price(symbol)
            if price is None or not session_for_symbol(symbol).is_open(now.to_pydatetime()):
                return
            candles = [(now, price, price, price)]
        else:
            candles = list(zip(bars.index, bars["open"], bars["high"], bars["low"]))
        with self._tx() as conn:
            for bar_time, o, h, low in candles:
                bar_ts = pd.Timestamp(bar_time).tz_convert("UTC")
                current = conn.execute(
                    f"""SELECT * FROM orders WHERE symbol = ?
                        AND status IN ({','.join('?' * len(OPEN_STATUSES))})
                        ORDER BY CASE type WHEN 'market' THEN 0 WHEN 'stop' THEN 1 ELSE 2 END, created_at""",
                    (symbol, *OPEN_STATUSES),
                ).fetchall()
                for row in current:
                    checked_from = pd.Timestamp(row["last_checked"] or row["created_at"]).floor("min")
                    if bar_ts < checked_from:
                        continue
                    # re-read: an OCO sibling may have just been filled/cancelled
                    fresh = conn.execute("SELECT * FROM orders WHERE id = ?", (row["id"],)).fetchone()
                    if fresh["status"] not in OPEN_STATUSES:
                        continue
                    order_type, side = OrderType(fresh["type"]), Side(fresh["side"])
                    fill = trigger_price(order_type, side, fresh["limit_price"], fresh["stop_price"], o, h, low)
                    if fill is None:
                        continue
                    if order_type in (OrderType.STOP, OrderType.MARKET):
                        fill *= 1 + self.slippage * side.sign
                    fill_time = max(bar_ts, pd.Timestamp(fresh["created_at"])).to_pydatetime()
                    self._fill(conn, fresh, fill, fill_time)
            last_bar = pd.Timestamp(candles[-1][0]).tz_convert("UTC")
            conn.execute(
                f"""UPDATE orders SET last_checked = ? WHERE symbol = ?
                    AND status IN ({','.join('?' * len(OPEN_STATUSES))})""",
                (_iso(min(last_bar, now).to_pydatetime()), symbol, *OPEN_STATUSES),
            )

    def is_market_open(self) -> bool | None:
        return None
