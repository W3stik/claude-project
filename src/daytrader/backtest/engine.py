"""Bar-by-bar backtester.

Execution model (deliberately conservative):
* signals are evaluated on the bar close and executed at the *next* bar's open,
* stop-loss and take-profit are checked intrabar; if both could have been hit in the
  same bar the stop is assumed first; gaps through a stop fill at the open,
* market fills pay slippage, take-profit (limit) fills don't,
* with ``eod_flatten`` every position is closed at the last bar of each session.
"""

from __future__ import annotations

import itertools
from dataclasses import asdict, dataclass, field
from typing import Any

import numpy as np
import pandas as pd

from ..analysis.indicators import atr as atr_indicator
from ..analysis.indicators import session_keys
from ..models import Side
from ..risk import position_size, stop_and_target
from ..sessions import is_crypto_symbol
from ..strategies import Strategy, get_strategy
from ..timeframes import is_intraday
from .metrics import METRIC_LABELS, equity_stats, format_metric, trade_stats


@dataclass
class BacktestConfig:
    initial_capital: float = 10_000.0
    risk_per_trade_pct: float = 1.0
    max_position_pct: float = 100.0
    stop_atr_mult: float | None = 1.5
    take_profit_r: float | None = 2.0
    atr_period: int = 14
    commission_per_share: float = 0.0
    commission_pct: float = 0.0
    min_commission: float = 0.0
    slippage_bps: float = 2.0
    allow_short: bool = True
    eod_flatten: bool = True
    fractional: bool = False
    periods_per_year: int = 252

    def commission(self, qty: float, price: float) -> float:
        if qty <= 0:
            return 0.0
        fee = qty * self.commission_per_share + qty * price * self.commission_pct / 100
        return max(fee, self.min_commission)

    @classmethod
    def from_settings(cls, settings: Any, symbol: str = "", **overrides: Any) -> "BacktestConfig":
        """Same sizing, stops and costs the live bot uses; ``None`` overrides keep the setting,
        ``0`` for ``stop_atr_mult`` / ``take_profit_r`` disables the stop / target."""
        crypto = is_crypto_symbol(symbol) if symbol else False
        values: dict[str, Any] = {
            "initial_capital": settings.paper_starting_cash,
            "risk_per_trade_pct": settings.risk_per_trade_pct,
            "max_position_pct": settings.max_position_pct,
            "stop_atr_mult": settings.stop_atr_mult or None,
            "take_profit_r": settings.take_profit_r or None,
            "commission_per_share": settings.paper_commission_per_share,
            "commission_pct": settings.paper_commission_pct,
            "min_commission": settings.paper_min_commission,
            "slippage_bps": settings.paper_slippage_bps,
            "allow_short": settings.allow_short,
            "fractional": crypto,
            "periods_per_year": 365 if crypto else 252,
        }
        for key, value in overrides.items():
            if value is None:
                continue
            if key in ("stop_atr_mult", "take_profit_r") and value == 0:
                value = None
            values[key] = value
        return cls(**values)


@dataclass
class Trade:
    side: str
    entry_time: pd.Timestamp
    exit_time: pd.Timestamp
    entry_price: float
    exit_price: float
    qty: float
    pnl: float
    pnl_pct: float
    r_multiple: float | None
    commission: float
    exit_reason: str
    bars_held: int
    stop: float | None = None
    target: float | None = None


EXIT_REASONS = {
    "signal": "signál",
    "stop": "stop-loss",
    "target": "take-profit",
    "eod": "konec dne",
    "end": "konec dat",
}


@dataclass
class BacktestResult:
    symbol: str
    interval: str
    strategy: str
    params: dict[str, Any]
    config: BacktestConfig
    bars: pd.DataFrame
    signals: pd.Series
    equity: pd.Series
    position: pd.Series
    trades: list[Trade] = field(default_factory=list)
    metrics: dict[str, Any] = field(default_factory=dict)

    def trades_df(self) -> pd.DataFrame:
        columns = list(Trade.__dataclass_fields__)
        return pd.DataFrame([asdict(t) for t in self.trades], columns=columns)

    def summary(self) -> list[tuple[str, str]]:
        return [(METRIC_LABELS.get(k, k), format_metric(k, v)) for k, v in self.metrics.items()]


def run_backtest(
    bars: pd.DataFrame,
    strategy: Strategy,
    config: BacktestConfig | None = None,
    symbol: str = "",
    interval: str = "",
) -> BacktestResult:
    config = config or BacktestConfig()
    if len(bars) < 3:
        raise ValueError("Na backtest je potřeba víc dat (alespoň pár desítek svíček).")
    if strategy.intraday_only and interval and not is_intraday(interval):
        raise ValueError(f"Strategie '{strategy.name}' vyžaduje intradenní interval (např. 5m).")

    signals = strategy.generate_signals(bars).reindex(bars.index).fillna(0).astype(int)
    if not config.allow_short:
        signals = signals.clip(lower=0)
    sig = signals.to_numpy()
    o, h, l, c = (bars[col].to_numpy(dtype=float) for col in ("open", "high", "low", "close"))
    atr_values = atr_indicator(bars, config.atr_period).to_numpy()
    keys = session_keys(bars.index)
    last_of_session = np.r_[keys[1:] != keys[:-1], True]
    slip = config.slippage_bps / 10_000
    n = len(bars)

    cash = float(config.initial_capital)
    qty = 0.0
    entry_price = entry_comm = 0.0
    entry_idx = 0
    stop: float | None = None
    target: float | None = None
    pending: int | None = None
    equity = np.empty(n)
    position = np.empty(n)
    trades: list[Trade] = []

    def close_position(i: int, price: float, reason: str) -> None:
        nonlocal cash, qty
        size = abs(qty)
        direction = 1 if qty > 0 else -1
        fee = config.commission(size, price)
        cash += qty * price - fee
        total_fee = entry_comm + fee
        pnl = (price - entry_price) * size * direction - total_fee
        risk = abs(entry_price - stop) * size if stop is not None else None
        trades.append(
            Trade(
                side="long" if direction > 0 else "short",
                entry_time=bars.index[entry_idx],
                exit_time=bars.index[i],
                entry_price=entry_price,
                exit_price=price,
                qty=size,
                pnl=pnl,
                pnl_pct=pnl / (entry_price * size) * 100,
                r_multiple=pnl / risk if risk else None,
                commission=total_fee,
                exit_reason=reason,
                bars_held=i - entry_idx + 1,
                stop=stop,
                target=target,
            )
        )
        qty = 0.0

    def open_position(i: int, direction: int) -> None:
        nonlocal cash, qty, entry_price, entry_comm, entry_idx, stop, target
        price = o[i] * (1 + slip * direction)
        side = Side.BUY if direction > 0 else Side.SELL
        atr_prev = atr_values[i - 1] if i > 0 else np.nan
        if config.stop_atr_mult:
            new_stop, new_target = stop_and_target(
                side, price, float(atr_prev), config.stop_atr_mult, config.take_profit_r
            )
            if new_stop is None:  # ATR not warmed up yet - never trade without the planned stop
                return
        else:
            new_stop, new_target = None, None
        size = position_size(
            cash, price, new_stop, config.risk_per_trade_pct, config.max_position_pct, config.fractional
        )
        if size <= 0:
            return
        fee = config.commission(size, price)
        cash -= direction * size * price + fee
        qty = direction * size
        entry_price, entry_comm, entry_idx = price, fee, i
        stop, target = new_stop, new_target

    for i in range(n):
        if pending is not None:
            direction, pending = pending, None
            if qty != 0:
                close_position(i, o[i] * (1 - slip * np.sign(qty)), "signal")
            if direction != 0:
                open_position(i, direction)

        if qty > 0:
            if stop is not None and l[i] <= stop:
                close_position(i, min(o[i], stop) * (1 - slip), "stop")
            elif target is not None and h[i] >= target:
                close_position(i, max(o[i], target), "target")
        elif qty < 0:
            if stop is not None and h[i] >= stop:
                close_position(i, max(o[i], stop) * (1 + slip), "stop")
            elif target is not None and l[i] <= target:
                close_position(i, min(o[i], target), "target")

        if qty != 0 and config.eod_flatten and last_of_session[i]:
            close_position(i, c[i] * (1 - slip * np.sign(qty)), "eod")

        equity[i] = cash + qty * c[i]
        position[i] = qty

        if i == n - 1:
            break
        s = int(sig[i])
        fresh = s != 0 and s != (int(sig[i - 1]) if i > 0 else 0)
        can_enter = not (config.eod_flatten and last_of_session[i])
        side_now = int(np.sign(qty))
        if side_now != 0 and s != side_now:
            pending = s if (fresh and can_enter) else 0
        elif side_now == 0 and fresh and can_enter:
            pending = s

    if qty != 0:
        close_position(n - 1, c[-1] * (1 - slip * np.sign(qty)), "end")
        equity[-1] = cash
        position[-1] = 0.0

    equity_series = pd.Series(equity, index=bars.index, name="equity")
    result = BacktestResult(
        symbol=symbol,
        interval=interval,
        strategy=strategy.name,
        params=dict(strategy.params),
        config=config,
        bars=bars,
        signals=signals,
        equity=equity_series,
        position=pd.Series(position, index=bars.index, name="position"),
        trades=trades,
    )
    metrics = equity_stats(equity_series, config.initial_capital, config.periods_per_year)
    metrics["buy_hold_return_pct"] = float((c[-1] / o[0] - 1) * 100)
    metrics["exposure_pct"] = float((position != 0).mean() * 100)
    metrics.update(trade_stats(result.trades_df()))
    result.metrics = metrics
    return result


def grid_search(
    bars: pd.DataFrame,
    strategy_key: str,
    grid: dict[str, list[Any]],
    config: BacktestConfig | None = None,
    interval: str = "",
    sort_by: str = "total_return_pct",
) -> pd.DataFrame:
    """Backtest every parameter combination. Beware: the best in-sample combination is
    usually overfitted - always confirm it on data it was not optimised on."""
    names = list(grid)
    rows = []
    for values in itertools.product(*(grid[name] for name in names)):
        params = dict(zip(names, values))
        try:
            strategy = get_strategy(strategy_key, **params)
        except ValueError:
            continue
        result = run_backtest(bars, strategy, config, interval=interval)
        m = result.metrics
        rows.append(
            {
                **params,
                "total_return_pct": m.get("total_return_pct"),
                "max_drawdown_pct": m.get("max_drawdown_pct"),
                "sharpe": m.get("sharpe"),
                "profit_factor": m.get("profit_factor"),
                "win_rate_pct": m.get("win_rate_pct"),
                "trades": m.get("trades"),
            }
        )
    frame = pd.DataFrame(rows)
    if not frame.empty and sort_by in frame:
        frame = frame.sort_values(sort_by, ascending=False, na_position="last").reset_index(drop=True)
    return frame
