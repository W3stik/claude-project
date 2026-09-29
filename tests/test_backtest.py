import pandas as pd
import pytest

from daytrader.backtest import BacktestConfig, grid_search, run_backtest
from daytrader.backtest.metrics import drawdown, trade_stats
from daytrader.strategies import Strategy

from .conftest import make_bars, make_session_bars


class Scripted(Strategy):
    """Test strategy returning a predefined target position series."""

    key = "scripted"
    name = "Scripted"
    description = ""

    def __init__(self, targets):
        super().__init__()
        self.targets = targets

    def generate_signals(self, bars):
        values = list(self.targets) + [self.targets[-1]] * (len(bars) - len(self.targets))
        return pd.Series(values[: len(bars)], index=bars.index)


def flat_bars(n=40, price=100.0, spread=0.5):
    return make_bars([price] * n, spread=spread)


NO_COSTS = dict(slippage_bps=0.0, eod_flatten=False, risk_per_trade_pct=1.0, max_position_pct=100.0)


def test_entry_on_next_open_and_stop_loss():
    closes = [100.0] * 20 + [100.0, 100.0, 97.0, 96.0]
    bars = make_bars(closes, spread=0.5)
    targets = [0] * 20 + [1] * 4  # signal at bar 20 close -> entry at bar 21 open
    result = run_backtest(bars, Scripted(targets), BacktestConfig(**NO_COSTS, stop_atr_mult=1.5, take_profit_r=None))
    trade = result.trades[0]
    assert trade.entry_time == bars.index[21]
    assert trade.entry_price == pytest.approx(100.0)
    assert trade.exit_reason == "stop"
    # ATR = 1.0 (constant 1-point range) -> stop 1.5 below entry
    assert trade.stop == pytest.approx(98.5)
    assert trade.exit_price == pytest.approx(98.5)
    assert trade.r_multiple == pytest.approx(-1.0)
    # 1 % of 10 000 = 100 risk / 1.5 distance -> 66 shares
    assert trade.qty == 66


def test_take_profit_hit():
    closes = [100.0] * 21 + [100.0, 102.0, 104.0]
    bars = make_bars(closes, spread=0.5)
    targets = [0] * 20 + [1] * 4
    result = run_backtest(bars, Scripted(targets), BacktestConfig(**NO_COSTS, stop_atr_mult=1.5, take_profit_r=2.0))
    trade = result.trades[0]
    assert trade.exit_reason == "target"
    assert trade.exit_price == pytest.approx(103.0)
    assert trade.r_multiple == pytest.approx(2.0)


def test_gap_through_stop_fills_at_open():
    closes = [100.0] * 22 + [95.0]
    opens = [100.0] * 22 + [95.0]
    bars = make_bars(closes, opens=opens, spread=0.5)
    result = run_backtest(bars, Scripted([0] * 20 + [1] * 3), BacktestConfig(**NO_COSTS, take_profit_r=None))
    assert result.trades[0].exit_price == pytest.approx(95.0)


def test_eod_flatten_closes_at_session_end_and_waits_for_fresh_signal():
    bars = make_session_bars([[100.0] * 20, [100.0] * 20], spread=0.5)
    targets = [0] * 18 + [1] * 22  # long signal on day 1, still "long" all of day 2
    config = BacktestConfig(slippage_bps=0, eod_flatten=True, stop_atr_mult=None, take_profit_r=None)
    result = run_backtest(bars, Scripted(targets), config)
    assert len(result.trades) == 1
    assert result.trades[0].exit_reason == "eod"
    assert result.trades[0].exit_time == bars.index[19]


def test_short_disabled_produces_no_short_trades(bars):
    targets = [0, -1, -1, 0, 1, 1, 0] * (len(bars) // 7 + 1)
    result = run_backtest(bars, Scripted(targets), BacktestConfig(allow_short=False))
    assert all(t.side == "long" for t in result.trades)


def test_equity_reconciles_with_trades_and_costs(bars):
    config = BacktestConfig(commission_per_share=0.01, min_commission=1.0, slippage_bps=3)
    from daytrader.strategies import get_strategy

    result = run_backtest(bars, get_strategy("ema_cross"), config)
    assert result.metrics["trades"] > 0
    net = sum(t.pnl for t in result.trades)
    assert result.equity.iloc[-1] == pytest.approx(config.initial_capital + net, rel=1e-9)
    assert result.metrics["commissions"] > 0


def test_no_signals_means_flat_equity():
    bars = flat_bars()
    result = run_backtest(bars, Scripted([0] * len(bars)), BacktestConfig())
    assert result.trades == []
    assert (result.equity == 10_000).all()


def test_grid_search_sorted(bars):
    table = grid_search(bars, "ema_cross", {"fast": [5, 9], "slow": [21, 30]}, BacktestConfig())
    assert len(table) == 4
    returns = table["total_return_pct"].tolist()
    assert returns == sorted(returns, reverse=True)


def test_intraday_only_strategy_rejects_daily_interval(bars):
    from daytrader.strategies import get_strategy

    with pytest.raises(ValueError):
        run_backtest(bars, get_strategy("vwap_trend"), interval="1d")


def test_metrics_helpers():
    equity = pd.Series([100, 110, 99, 120, 108], dtype=float)
    dd = drawdown(equity)
    assert dd.min() == pytest.approx((99 / 110 - 1) * 100)
    stats = trade_stats(pd.DataFrame({"pnl": [10.0, -5.0, -5.0, 20.0]}))
    assert stats["profit_factor"] == pytest.approx(3.0)
    assert stats["win_rate_pct"] == 50
    assert stats["max_consecutive_losses"] == 2
    assert stats["payoff_ratio"] == pytest.approx(3.0)


def test_config_from_settings_uses_live_risk_rules():
    from daytrader.config import Settings

    settings = Settings(max_position_pct=25, risk_per_trade_pct=0.5, allow_short=False, stop_atr_mult=2.0)
    config = BacktestConfig.from_settings(settings, "BTC/USDT", take_profit_r=0, slippage_bps=None)
    assert config.max_position_pct == 25 and config.risk_per_trade_pct == 0.5 and not config.allow_short
    assert config.stop_atr_mult == 2.0 and config.take_profit_r is None  # 0 disables the target
    assert config.slippage_bps == settings.paper_slippage_bps  # None keeps the setting
    assert config.fractional and config.periods_per_year == 365
