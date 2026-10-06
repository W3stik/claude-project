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


def test_bot_page_switches_to_minute_trading(monkeypatch):
    monkeypatch.setenv("DT_DATA_PROVIDER", "demo")
    get_settings.cache_clear()

    def page():
        from daytrader.dashboard.views import bot_page

        bot_page()

    app = AppTest.from_function(page, default_timeout=120)
    app.run()
    assert not app.exception, [e.value for e in app.exception]
    widget = {w.label: w for w in [*app.selectbox, *app.number_input]}
    assert widget["Interval"].value == "5m" and widget["Max. obchodů za den"].value == 10
    widget["Strategie"].select("scalp").run()
    assert not app.exception, [e.value for e in app.exception]
    widget = {w.label: w for w in [*app.selectbox, *app.number_input]}
    assert widget["Interval"].value == "1m" and widget["Max. obchodů za den"].value == 100
    assert any("max. 3 pozic najednou, každá do 25 %" in c.value for c in app.caption)
    widget["Max. pozic najednou"].set_value(5).run()
    assert any("max. 5 pozic najednou, každá do 20 %" in c.value for c in app.caption)
    assert next(c for c in app.checkbox if c.label.startswith("Povolit short")).value is False


def test_strategy_parameter_inputs_render_for_every_strategy(monkeypatch):
    from daytrader.strategies import STRATEGIES

    monkeypatch.setenv("DT_DATA_PROVIDER", "demo")
    get_settings.cache_clear()

    def page():
        from daytrader.dashboard.views import bot_page

        bot_page()

    app = AppTest.from_function(page, default_timeout=120)
    app.run()
    for key in STRATEGIES:
        next(w for w in app.selectbox if w.label == "Strategie").select(key).run()
        assert not app.exception, (key, [e.value for e in app.exception])
