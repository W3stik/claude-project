from pathlib import Path

import pytest

pytest.importorskip("streamlit")
from streamlit.testing.v1 import AppTest  # noqa: E402

import daytrader.dashboard as dashboard_pkg  # noqa: E402
from daytrader.config import get_settings  # noqa: E402
from daytrader.dashboard import charts  # noqa: E402

APP = str(Path(dashboard_pkg.__file__).parent / "app.py")


def test_dashboard_main_page_renders(monkeypatch):
    monkeypatch.setenv("DT_DATA_PROVIDER", "demo")
    get_settings.cache_clear()
    app = AppTest.from_file(APP, default_timeout=120)
    app.run()
    assert not app.exception, [e.value for e in app.exception]
    assert [t.value for t in app.title] == ["Analýza"]
    labels = [m.label for m in app.metric]
    assert "Technické skóre" in labels and "RSI (14)" in labels


@pytest.mark.parametrize("mode", ["light", "dark"])
def test_charts_build(bars, mode):
    from daytrader.analysis import add_indicators
    from daytrader.backtest import run_backtest
    from daytrader.sessions import SESSIONS
    from daytrader.strategies import get_strategy

    df = add_indicators(bars)
    fig = charts.price_chart(df, mode, charts.OVERLAYS, "5m", SESSIONS["us"])
    assert len(fig.data) >= 6
    assert fig.layout.paper_bgcolor == charts.PALETTES[mode]["surface"]
    result = run_backtest(bars, get_strategy("ema_cross"))
    trades = result.trades_df()
    fig = charts.price_chart(df, mode, trades=trades, show_rsi=False, show_macd=False)
    assert any(trace.name == "Výstup" for trace in fig.data)
    assert charts.equity_chart(result.equity, mode=mode).data
