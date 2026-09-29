"""Performance statistics for equity curves and lists of closed trades."""

from __future__ import annotations

import math
from typing import Any

import numpy as np
import pandas as pd


def _finite(value: float) -> float | None:
    return float(value) if value is not None and math.isfinite(value) else None


def drawdown(equity: pd.Series) -> pd.Series:
    """Drawdown in percent from the running peak (0 at new highs, negative below)."""
    peak = equity.cummax()
    return (equity / peak - 1) * 100


def daily_equity(equity: pd.Series) -> pd.Series:
    if equity.empty:
        return equity
    keys = pd.Index(np.asarray(equity.index.date), name="date")
    return equity.groupby(keys).last()


def equity_stats(equity: pd.Series, initial_capital: float, periods_per_year: int = 252) -> dict[str, Any]:
    if equity.empty:
        return {}
    final = float(equity.iloc[-1])
    daily = daily_equity(equity)
    daily_returns = pd.concat([pd.Series([initial_capital]), daily.reset_index(drop=True)]).pct_change().dropna()
    std = daily_returns.std(ddof=1) if len(daily_returns) > 1 else float("nan")
    downside = daily_returns[daily_returns < 0]
    downside_std = math.sqrt((downside**2).mean()) if len(downside) else float("nan")
    mean = daily_returns.mean() if len(daily_returns) else float("nan")
    days = (equity.index[-1] - equity.index[0]).days
    years = days / 365.25
    total_return = final / initial_capital - 1
    return {
        "final_equity": final,
        "total_return_pct": total_return * 100,
        "cagr_pct": _finite(((final / initial_capital) ** (1 / years) - 1) * 100) if years >= 0.25 and final > 0 else None,
        "max_drawdown_pct": float(drawdown(equity).min()),
        "sharpe": _finite(mean / std * math.sqrt(periods_per_year)) if std and std > 0 else None,
        "sortino": _finite(mean / downside_std * math.sqrt(periods_per_year)) if downside_std and downside_std > 0 else None,
        "trading_days": int(len(daily)),
        "best_day_pct": _finite(daily_returns.max() * 100) if len(daily_returns) else None,
        "worst_day_pct": _finite(daily_returns.min() * 100) if len(daily_returns) else None,
    }


def trade_stats(trades: pd.DataFrame) -> dict[str, Any]:
    """Statistics over closed trades (expects columns ``pnl`` and optionally ``r_multiple``,
    ``bars_held``, ``commission``, ``side``)."""
    n = len(trades)
    if n == 0:
        return {"trades": 0}
    pnl = trades["pnl"].astype(float)
    wins = pnl[pnl > 0]
    losses = pnl[pnl <= 0]
    gross_profit = float(wins.sum())
    gross_loss = float(-losses.sum())
    avg_win = float(wins.mean()) if len(wins) else 0.0
    avg_loss = float(losses.mean()) if len(losses) else 0.0
    stats: dict[str, Any] = {
        "trades": n,
        "win_rate_pct": len(wins) / n * 100,
        "net_pnl": float(pnl.sum()),
        "gross_profit": gross_profit,
        "gross_loss": gross_loss,
        "profit_factor": _finite(gross_profit / gross_loss) if gross_loss > 0 else None,
        "expectancy": float(pnl.mean()),
        "avg_win": avg_win,
        "avg_loss": avg_loss,
        "payoff_ratio": _finite(avg_win / abs(avg_loss)) if avg_loss < 0 else None,
        "best_trade": float(pnl.max()),
        "worst_trade": float(pnl.min()),
        "max_consecutive_losses": _max_streak(pnl <= 0),
    }
    if "r_multiple" in trades and trades["r_multiple"].notna().any():
        stats["avg_r"] = float(trades["r_multiple"].mean())
    if "bars_held" in trades:
        stats["avg_bars_held"] = float(trades["bars_held"].mean())
    if "commission" in trades:
        stats["commissions"] = float(trades["commission"].sum())
    if "side" in trades:
        stats["long_trades"] = int((trades["side"] == "long").sum())
        stats["short_trades"] = int((trades["side"] == "short").sum())
    return stats


def _max_streak(mask: pd.Series) -> int:
    best = current = 0
    for flag in mask.to_numpy():
        current = current + 1 if flag else 0
        best = max(best, current)
    return best


METRIC_LABELS: dict[str, str] = {
    "final_equity": "Konečný kapitál",
    "total_return_pct": "Celkový výnos %",
    "buy_hold_return_pct": "Buy & hold výnos %",
    "cagr_pct": "Roční výnos (CAGR) %",
    "max_drawdown_pct": "Max. propad %",
    "sharpe": "Sharpe ratio",
    "sortino": "Sortino ratio",
    "exposure_pct": "Čas v pozici %",
    "trading_days": "Obchodních dní",
    "best_day_pct": "Nejlepší den %",
    "worst_day_pct": "Nejhorší den %",
    "trades": "Počet obchodů",
    "win_rate_pct": "Úspěšnost %",
    "net_pnl": "Čistý zisk/ztráta",
    "gross_profit": "Hrubý zisk",
    "gross_loss": "Hrubá ztráta",
    "profit_factor": "Profit factor",
    "expectancy": "Průměr na obchod",
    "avg_win": "Průměrný zisk",
    "avg_loss": "Průměrná ztráta",
    "payoff_ratio": "Poměr zisk/ztráta",
    "best_trade": "Nejlepší obchod",
    "worst_trade": "Nejhorší obchod",
    "max_consecutive_losses": "Max. ztrát v řadě",
    "avg_r": "Průměrné R",
    "avg_bars_held": "Průměrná délka (svíčky)",
    "commissions": "Poplatky celkem",
    "long_trades": "Long obchodů",
    "short_trades": "Short obchodů",
}


def format_metric(key: str, value: Any) -> str:
    if value is None or (isinstance(value, float) and not math.isfinite(value)):
        return "—"
    if isinstance(value, (int, np.integer)) and not isinstance(value, bool):
        return f"{int(value)}"
    if key.endswith("_pct"):
        return f"{value:.2f} %"
    if key in ("sharpe", "sortino", "profit_factor", "payoff_ratio", "avg_r", "avg_bars_held"):
        return f"{value:.2f}"
    return f"{value:,.2f}".replace(",", " ")
