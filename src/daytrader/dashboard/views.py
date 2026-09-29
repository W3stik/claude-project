"""Dashboard pages."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pandas as pd
import streamlit as st

from ..ai import AIAnalyst
from ..analysis.indicators import add_indicators
from ..analysis.snapshot import build_snapshot
from ..backtest import EXIT_REASONS, BacktestConfig, grid_search, run_backtest
from ..backtest.metrics import METRIC_LABELS, format_metric
from ..bot import BotConfig, TradingBot
from ..brokers import create_broker
from ..brokers.paper import PaperBroker
from ..config import parse_symbols
from ..data import create_provider
from ..journal import Journal, daily_pnl, journal_stats, round_trips
from ..models import OrderType, Side
from ..risk import RiskConfig, RiskManager
from ..scanner import scan
from ..sessions import is_crypto_symbol, session_for_symbol
from ..strategies import STRATEGIES, get_strategy
from ..timeframes import INTERVALS, PERIODS
from ..trading import execute_plan, plan_order
from . import charts
from .common import (
    bot_runner,
    broker_name,
    fmt,
    get_broker,
    get_journal,
    get_provider,
    guard,
    load_bars,
    load_news,
    local_time,
    polarity,
    provider_name,
    settings,
    theme_mode,
)

LEVEL_NAMES = {
    "prev_high": "Včerejší maximum",
    "prev_low": "Včerejší minimum",
    "prev_close": "Včerejší závěr",
    "today_open": "Dnešní otevírací",
    "today_high": "Dnešní maximum",
    "today_low": "Dnešní minimum",
    "pivot_R2": "Pivot R2",
    "pivot_R1": "Pivot R1",
    "pivot_P": "Pivot P",
    "pivot_S1": "Pivot S1",
    "pivot_S2": "Pivot S2",
}


def _risk() -> RiskManager:
    return RiskManager(RiskConfig.from_settings(settings()))


def _default_symbol() -> str:
    watch = settings().watchlist_symbols
    return st.session_state.get("symbol") or (watch[0] if watch else "AAPL")


def _plotly(fig) -> None:
    st.plotly_chart(fig, theme=None, config={"displaylogo": False, "scrollZoom": True})


# ---------------------------------------------------------------------------------------
# Analysis
# ---------------------------------------------------------------------------------------
def analysis_page() -> None:
    st.title("Analýza")
    cfg = settings()
    c1, c2, c3, c4 = st.columns([2, 1, 1, 3])
    symbol = c1.text_input("Symbol", value=_default_symbol(), help="Např. AAPL, SPY, CEZ.PR (Praha), SAP.DE, BTC-USD").strip().upper()
    interval = c2.selectbox("Interval", INTERVALS, index=INTERVALS.index("5m"))
    period = c3.selectbox("Období", PERIODS, index=PERIODS.index("5d"))
    overlays = c4.multiselect("Překryvy v grafu", charts.OVERLAYS, default=charts.OVERLAYS[:3])
    if not symbol:
        st.stop()
    st.session_state["symbol"] = symbol

    with guard():
        bars = load_bars(provider_name(), symbol, interval, period)
        snap = build_snapshot(bars, symbol, interval, stop_atr_mult=cfg.stop_atr_mult)
    provider = get_provider(provider_name())
    warning = getattr(provider, "last_warning", None)
    if warning:
        st.info(warning)

    m = st.columns(6)
    m[0].metric("Cena", fmt(snap.price), f"{snap.change_pct:+.2f} %" if snap.change_pct is not None else None,
                delta_color=polarity(snap.change_pct), border=True)
    m[1].metric("Technické skóre", f"{snap.score:+d}", snap.bias, delta_color=polarity(snap.score), delta_arrow="off",
                border=True, help="Souhrn trendu, VWAP, MACD, RSI a delšího trendu v rozsahu −100 až +100.")
    arrow = {"rostoucí": "↗", "klesající": "↘"}.get(snap.trend, "→")
    m[2].metric("Trend", arrow, snap.trend, delta_color="off", delta_arrow="off", border=True)
    m[3].metric("RSI (14)", fmt(snap.rsi, 1), border=True)
    m[4].metric("ATR", fmt(snap.atr), f"{snap.atr_pct:.2f} % ceny" if snap.atr_pct else None, delta_color="off", border=True)
    m[5].metric("Relativní objem", fmt(snap.rvol, 2, "×"), border=True,
                help="Objem dnešní seance vůči průměru předchozích dní ve stejný čas.")

    indicators = add_indicators(bars)
    session = None if is_crypto_symbol(symbol) else session_for_symbol(symbol)
    _plotly(charts.price_chart(indicators, theme_mode(), overlays, interval, session))

    left, right = st.columns([3, 2])
    with left:
        st.subheader("Technický přehled")
        st.markdown("\n".join(f"- {line}" for line in snap.signals))
    with right:
        st.subheader("Důležité úrovně")
        rows = [(label, snap.levels[key]) for key, label in LEVEL_NAMES.items() if key in snap.levels]
        rows += [("Rezistence (swing)", v) for v in snap.swing.get("resistance", [])]
        rows += [("Support (swing)", v) for v in snap.swing.get("support", [])]
        if rows:
            levels = pd.DataFrame(rows, columns=["Úroveň", "Cena"])
            levels["Vzdálenost %"] = (levels["Cena"] / snap.price - 1) * 100
            st.dataframe(levels, hide_index=True, column_config={
                "Cena": st.column_config.NumberColumn(format="%.2f"),
                "Vzdálenost %": st.column_config.NumberColumn(format="%+.2f %%"),
            })
        else:
            st.caption("Úrovně jsou k dispozici pro intradenní intervaly.")

    with st.expander("Data v tabulce"):
        table = indicators[["open", "high", "low", "close", "volume", "ema9", "ema21", "vwap", "rsi", "atr"]].tail(300)
        table.index = table.index.tz_localize(None)
        st.dataframe(table.iloc[::-1], column_config={c: st.column_config.NumberColumn(format="%.2f") for c in table.columns})

    news = load_news(provider_name(), symbol)
    if news:
        st.subheader("Zprávy")
        for item in news:
            when = item.published.strftime("%d.%m. %H:%M") if item.published else ""
            title = f"[{item.title}]({item.url})" if item.url else item.title
            st.markdown(f"- {title}  \n  <small>{item.source or ''} {when}</small>", unsafe_allow_html=True)

    st.subheader("AI komentář")
    if not cfg.has_ai:
        st.caption("Volitelné a placené podle spotřeby: vyplň ANTHROPIC_API_KEY v souboru .env (viz README).")
        return
    question = st.text_input("Otázka pro AI analytika (nepovinné)", placeholder="Např. kde má smysl stop-loss pro long?")
    key = f"ai::{symbol}::{interval}::{snap.timestamp}::{question}"
    if st.button("Vygenerovat AI komentář", icon="🤖", help=f"Model {cfg.ai_model}; stojí zhruba jednotky centů za dotaz."):
        with guard(), st.spinner("AI analytik přemýšlí…"):
            analyst = AIAnalyst(cfg.anthropic_api_key.get_secret_value(), cfg.ai_model, cfg.ai_effort)
            st.session_state[key] = analyst.analyze(snap.to_dict(), news, question or None)
    result = st.session_state.get(key)
    if result is not None:
        with st.container(border=True):
            st.markdown(result.text)
            cost = result.estimated_cost_usd
            st.caption(
                f"{result.model} · {result.input_tokens} + {result.output_tokens} tokenů"
                + (f" · cca ${cost:.3f}" if cost is not None else "")
                + " · Nejde o investiční doporučení."
            )


# ---------------------------------------------------------------------------------------
# Scanner
# ---------------------------------------------------------------------------------------
def scanner_page() -> None:
    st.title("Scanner")
    st.caption("Najde tituly, které se právě hýbou: skóre trendu/momenta, relativní objem, gap, vzdálenost od VWAP.")
    cfg = settings()
    with st.form("scan"):
        symbols_text = st.text_area("Symboly", value=", ".join(cfg.watchlist_symbols), height=80)
        c1, c2, c3 = st.columns(3)
        interval = c1.selectbox("Interval", INTERVALS, index=INTERVALS.index("5m"))
        period = c2.selectbox("Období", PERIODS, index=PERIODS.index("5d"))
        keys = ["—", *STRATEGIES]
        strategy_key = c3.selectbox("Signál strategie", keys, format_func=lambda k: STRATEGIES[k].name if k in STRATEGIES else "—")
        submitted = st.form_submit_button("Skenovat", type="primary")
    if submitted:
        symbols = parse_symbols(symbols_text)
        with guard(), st.spinner(f"Skenuji {len(symbols)} symbolů…"):
            strategy = get_strategy(strategy_key) if strategy_key in STRATEGIES else None
            st.session_state["scan_result"] = scan(symbols, get_provider(provider_name()), interval, period, strategy)
    result = st.session_state.get("scan_result")
    if result is None:
        st.info("Zadej symboly a klikni na Skenovat.")
        return
    view = result.rename(columns={
        "symbol": "Symbol", "price": "Cena", "change_pct": "Změna %", "gap_pct": "Gap %", "rvol": "RVOL",
        "rsi": "RSI", "atr_pct": "ATR %", "vs_vwap_pct": "vs VWAP %", "trend": "Trend", "score": "Skóre",
        "bias": "Nálada", "signal": "Signál", "error": "Chyba",
    })
    view["Signál"] = view["Signál"].map({1: "LONG", -1: "SHORT", 0: "—"})
    empty = [c for c in ("Signál", "Chyba") if view[c].isna().all()]
    view = view.drop(columns=empty)
    event = st.dataframe(
        view, hide_index=True, on_select="rerun", selection_mode="single-row",
        column_config={
            "Cena": st.column_config.NumberColumn(format="%.2f"),
            "Změna %": st.column_config.NumberColumn(format="%+.2f"),
            "Gap %": st.column_config.NumberColumn(format="%+.2f"),
            "RVOL": st.column_config.NumberColumn(format="%.2f×"),
            "RSI": st.column_config.NumberColumn(format="%.0f"),
            "ATR %": st.column_config.NumberColumn(format="%.2f"),
            "vs VWAP %": st.column_config.NumberColumn(format="%+.2f"),
            "Skóre": st.column_config.NumberColumn(format="%+d"),
        },
    )
    rows = event.selection.rows if event and event.selection else []
    if rows:
        chosen = view.iloc[rows[0]]["Symbol"]
        if st.button(f"Otevřít {chosen} v analýze", type="primary"):
            st.session_state["symbol"] = chosen
            st.switch_page(st.session_state["_pages"]["analysis"])


# ---------------------------------------------------------------------------------------
# Backtest
# ---------------------------------------------------------------------------------------
def _strategy_params(strategy_key: str, prefix: str) -> dict:
    params = {}
    spec = STRATEGIES[strategy_key].params_spec
    cols = st.columns(max(1, min(4, len(spec))))
    for i, p in enumerate(spec):
        col = cols[i % len(cols)]
        key = f"{prefix}_{strategy_key}_{p.name}"
        if isinstance(p.default, bool):
            params[p.name] = col.checkbox(p.description, value=p.default, key=key)
        elif isinstance(p.default, int):
            params[p.name] = int(col.number_input(p.description, value=p.default, min_value=int(p.min) if p.min is not None else None,
                                                  max_value=int(p.max) if p.max is not None else None,
                                                  step=int(p.step or 1), key=key))
        else:
            params[p.name] = float(col.number_input(p.description, value=float(p.default), min_value=p.min, max_value=p.max,
                                                    step=float(p.step or 0.1), key=key))
    return params


def backtest_page() -> None:
    st.title("Backtest")
    st.caption("Otestuj strategii na historii dřív, než do ní vložíš peníze. Signál na zavření svíčky, vstup na otevření další.")
    tab_run, tab_opt = st.tabs(["Backtest", "Optimalizace parametrů"])

    with tab_run:
        c1, c2, c3, c4 = st.columns(4)
        symbol = c1.text_input("Symbol", value=_default_symbol(), key="bt_symbol").strip().upper()
        interval = c2.selectbox("Interval", INTERVALS, index=INTERVALS.index("5m"), key="bt_interval")
        period = c3.selectbox("Období", PERIODS, index=PERIODS.index("1mo"), key="bt_period")
        strategy_key = c4.selectbox("Strategie", list(STRATEGIES), format_func=lambda k: STRATEGIES[k].name, key="bt_strategy")
        st.caption(STRATEGIES[strategy_key].description)
        params = _strategy_params(strategy_key, "bt")
        cfg = settings()
        with st.expander("Řízení rizika a náklady (výchozí hodnoty z nastavení bota)", expanded=False):
            r1, r2, r3, r4 = st.columns(4)
            capital = r1.number_input("Počáteční kapitál", value=float(cfg.paper_starting_cash), min_value=100.0, step=1000.0)
            risk_pct = r2.number_input("Riziko na obchod %", value=float(cfg.risk_per_trade_pct), min_value=0.1, max_value=10.0, step=0.1)
            stop_atr = r3.number_input("Stop-loss (× ATR, 0 = bez)", value=float(cfg.stop_atr_mult), min_value=0.0, step=0.25)
            tp_r = r4.number_input("Take-profit (× R, 0 = bez)", value=float(cfg.take_profit_r), min_value=0.0, step=0.25)
            r5, r6, r7, r8 = st.columns(4)
            commission_share = r5.number_input("Poplatek za kus", value=float(cfg.paper_commission_per_share), min_value=0.0,
                                               step=0.005, format="%.3f")
            commission_pct = r6.number_input("Poplatek % z objemu", value=float(cfg.paper_commission_pct), min_value=0.0, step=0.01)
            slippage = r7.number_input("Skluz (bp)", value=float(cfg.paper_slippage_bps), min_value=0.0, step=0.5, help="1 bp = 0,01 %")
            max_pos = r8.number_input("Max. pozice % kapitálu", value=float(cfg.max_position_pct), min_value=1.0, max_value=400.0, step=5.0)
            s1, s2 = st.columns(2)
            allow_short = s1.toggle("Povolit short", value=cfg.allow_short)
            eod = s2.toggle("Zavírat pozice na konci dne", value=True)
        if st.button("Spustit backtest", type="primary"):
            config = BacktestConfig.from_settings(
                cfg, symbol, initial_capital=capital, risk_per_trade_pct=risk_pct, max_position_pct=max_pos,
                stop_atr_mult=stop_atr, take_profit_r=tp_r, commission_per_share=commission_share,
                commission_pct=commission_pct, slippage_bps=slippage, allow_short=allow_short, eod_flatten=eod,
            )
            with guard(), st.spinner("Počítám…"):
                bars = load_bars(provider_name(), symbol, interval, period)
                st.session_state["bt_result"] = run_backtest(bars, get_strategy(strategy_key, **params), config, symbol, interval)
        result = st.session_state.get("bt_result")
        if result is not None:
            _show_backtest(result)

    with tab_opt:
        _optimization_tab()


def _show_backtest(result) -> None:
    m = result.metrics
    st.subheader(f"{result.symbol} · {result.strategy} · {result.interval}")
    cols = st.columns(6)
    cols[0].metric("Výnos strategie", format_metric("total_return_pct", m.get("total_return_pct")), border=True)
    cols[1].metric("Buy & hold", format_metric("buy_hold_return_pct", m.get("buy_hold_return_pct")), border=True,
                   help="Výnos při prostém nákupu na začátku a držení do konce – měřítko pro srovnání.")
    cols[2].metric("Max. propad", format_metric("max_drawdown_pct", m.get("max_drawdown_pct")), border=True)
    cols[3].metric("Profit factor", format_metric("profit_factor", m.get("profit_factor")), border=True,
                   help="Hrubý zisk / hrubá ztráta. Nad 1,3 je zajímavé, pod 1 ztrátové.")
    cols[4].metric("Úspěšnost", format_metric("win_rate_pct", m.get("win_rate_pct")), border=True)
    cols[5].metric("Obchodů", format_metric("trades", m.get("trades")), border=True)
    if m.get("trades", 0) < 30:
        st.warning("Méně než 30 obchodů – výsledek je statisticky slabý. Prodluž období nebo zkus jiný symbol.")
    session = None if is_crypto_symbol(result.symbol) else session_for_symbol(result.symbol)
    bench = result.bars["close"] / result.bars["open"].iloc[0] * result.config.initial_capital
    _plotly(charts.equity_chart(result.equity, bench, theme_mode(), interval=result.interval, session=session))
    trades = result.trades_df()
    if len(result.bars) <= 6000:
        indicators = add_indicators(result.bars)
        _plotly(charts.price_chart(indicators, theme_mode(), ["EMA 9", "EMA 21", "VWAP"], result.interval, session,
                                   show_rsi=False, show_macd=False, trades=trades, height=560, title="Obchody v grafu"))
    if not trades.empty:
        st.subheader("Obchody")
        view = trades.copy()
        view["exit_reason"] = view["exit_reason"].map(EXIT_REASONS).fillna(view["exit_reason"])
        for column in ("entry_time", "exit_time"):
            view[column] = view[column].dt.tz_localize(None)
        view = view.rename(columns={
            "side": "Směr", "entry_time": "Vstup", "exit_time": "Výstup", "entry_price": "Cena vstupu",
            "exit_price": "Cena výstupu", "qty": "Množství", "pnl": "P/L", "pnl_pct": "P/L %", "r_multiple": "R",
            "commission": "Poplatky", "exit_reason": "Důvod výstupu", "bars_held": "Svíček", "stop": "Stop", "target": "Cíl",
        })
        st.dataframe(view.iloc[::-1], hide_index=True, column_config={
            c: st.column_config.NumberColumn(format="%.2f") for c in ("Cena vstupu", "Cena výstupu", "P/L", "P/L %", "R", "Poplatky", "Stop", "Cíl")
        })
        st.download_button("Stáhnout obchody (CSV)", trades.to_csv(index=False).encode("utf-8"),
                           file_name=f"backtest_{result.symbol}.csv", mime="text/csv")
    with st.expander("Všechny metriky"):
        st.dataframe(pd.DataFrame(result.summary(), columns=["Metrika", "Hodnota"]), hide_index=True)
    st.caption("Minulé výsledky nezaručují budoucí. Čím víc parametrů ladíš, tím víc riskuješ přeoptimalizování.")


def _optimization_tab() -> None:
    st.caption("Zkouší kombinace parametrů na starší části dat a nejlepší ověří na novějších datech, která optimalizace neviděla.")
    c1, c2, c3, c4 = st.columns(4)
    symbol = c1.text_input("Symbol", value=_default_symbol(), key="opt_symbol").strip().upper()
    interval = c2.selectbox("Interval", INTERVALS, index=INTERVALS.index("5m"), key="opt_interval")
    period = c3.selectbox("Období", PERIODS, index=PERIODS.index("1mo"), key="opt_period")
    strategy_key = c4.selectbox("Strategie", list(STRATEGIES), format_func=lambda k: STRATEGIES[k].name, key="opt_strategy")
    spec = STRATEGIES[strategy_key].params_spec
    grid_text = {}
    cols = st.columns(max(1, min(4, len(spec))))
    for i, p in enumerate(spec):
        default = ", ".join(str(v) for v in _default_grid(p))
        grid_text[p.name] = cols[i % len(cols)].text_input(f"{p.description} ({p.name})", value=default, key=f"opt_{strategy_key}_{p.name}")
    holdout = st.slider("Odložená data pro ověření", 0.1, 0.5, 0.3, 0.05, format="%.2f")
    if st.button("Spustit optimalizaci", type="primary"):
        with guard(), st.spinner("Počítám kombinace…"):
            grid = {}
            for p in spec:
                values = [v.strip() for v in grid_text[p.name].split(",") if v.strip()]
                grid[p.name] = [p.coerce(v) for v in values] or [p.default]
            bars = load_bars(provider_name(), symbol, interval, period)
            days = pd.Index(bars.index.date).unique()
            split = max(1, int(len(days) * (1 - holdout)))
            in_sample = bars[pd.Index(bars.index.date).isin(days[:split])]
            out_sample = bars[pd.Index(bars.index.date).isin(days[split:])]
            config = BacktestConfig.from_settings(settings(), symbol)
            table = grid_search(in_sample, strategy_key, grid, config, interval)
            if table.empty:
                raise ValueError("Žádná platná kombinace parametrů.")
            best = {p.name: table.iloc[0][p.name] for p in spec}
            test = run_backtest(out_sample, get_strategy(strategy_key, **best), config, symbol, interval) if len(out_sample) > 30 else None
            st.session_state["opt_result"] = (table, best, test)
    stored = st.session_state.get("opt_result")
    if stored:
        table, best, test = stored
        st.dataframe(table.head(25), hide_index=True)
        if test is not None:
            st.subheader(f"Ověření nejlepší kombinace {best} na odložených datech")
            cols = st.columns(4)
            for col, key in zip(cols, ("total_return_pct", "max_drawdown_pct", "profit_factor", "trades")):
                col.metric(METRIC_LABELS[key], format_metric(key, test.metrics.get(key)), border=True)
            st.caption("Pokud je výsledek na odložených datech výrazně horší, parametry jsou přeoptimalizované.")


def _default_grid(param) -> list:
    if isinstance(param.default, bool):
        return [True, False]
    if isinstance(param.default, int):
        base = param.default
        values = sorted({max(int(param.min or 1), round(base * f)) for f in (0.6, 1.0, 1.5)})
        return values
    return [param.default]


# ---------------------------------------------------------------------------------------
# Trading
# ---------------------------------------------------------------------------------------
def trading_page() -> None:
    st.title("Obchodování")
    with guard():
        broker = get_broker(broker_name(), provider_name())
    if broker.is_live:
        st.error("ŽIVÝ ÚČET – příkazy pracují se skutečnými penězi.", icon="⚠️")
    else:
        st.info(f"{broker.name}: papírový / testovací účet – bez finančního rizika.", icon="🧪")

    auto = st.toggle("Automaticky obnovovat každých 30 s", value=False)

    @st.fragment(run_every="30s" if auto else None)
    def account_section() -> None:
        with guard():
            broker.sync()
            account = broker.get_account()
            positions = broker.get_positions()
            orders = broker.get_orders("open")
        cols = st.columns(4)
        cols[0].metric("Kapitál", fmt(account.equity), border=True)
        cols[1].metric("Hotovost", fmt(account.cash), border=True)
        cols[2].metric("Kupní síla", fmt(account.buying_power), border=True)
        cols[3].metric("Dnešní P/L", fmt(account.day_pnl), f"{account.day_pnl_pct:+.2f} %" if account.day_pnl_pct is not None else None,
                       delta_color=polarity(account.day_pnl), border=True)
        risk = _risk()
        if risk.daily_loss_hit(account):
            st.error(f"Denní limit ztráty {risk.config.max_daily_loss_pct:g} % je vyčerpán – dnes už nové obchody neotvírej.")

        st.subheader("Pozice")
        if positions:
            frame = pd.DataFrame([p.to_row() for p in positions]).rename(columns={
                "symbol": "Symbol", "side": "Směr", "qty": "Množství", "avg_price": "Prům. cena",
                "current_price": "Aktuální", "market_value": "Hodnota", "unrealized_pnl": "P/L", "unrealized_pnl_pct": "P/L %",
            })
            st.dataframe(frame, hide_index=True, column_config={
                c: st.column_config.NumberColumn(format="%.2f") for c in ("Prům. cena", "Aktuální", "Hodnota", "P/L", "P/L %")
            })
            c1, c2, c3 = st.columns([2, 1, 1])
            target = c1.selectbox("Pozice", [p.symbol for p in positions], label_visibility="collapsed")
            if c2.button("Uzavřít pozici"):
                with guard():
                    broker.close_position(target)
                st.rerun()
            if c3.button("Uzavřít vše"):
                with guard():
                    broker.close_all()
                st.rerun()
        else:
            st.caption("Žádné otevřené pozice.")

        st.subheader("Otevřené příkazy")
        if orders:
            frame = pd.DataFrame([o.to_row() for o in orders])[
                ["id", "created_at", "symbol", "side", "type", "qty", "limit_price", "stop_price", "status", "parent_id"]
            ]
            frame["created_at"] = local_time(frame["created_at"])
            frame = frame.rename(columns={
                "id": "ID", "created_at": "Čas", "symbol": "Symbol", "side": "Strana", "type": "Typ", "qty": "Množství",
                "limit_price": "Limit", "stop_price": "Stop", "status": "Stav", "parent_id": "Vstupní příkaz",
            })
            st.dataframe(frame, hide_index=True, column_config={
                "Limit": st.column_config.NumberColumn(format="%.4f"), "Stop": st.column_config.NumberColumn(format="%.4f"),
            })
            c1, c2 = st.columns([3, 1])
            chosen = c1.selectbox("Příkaz", [o.id for o in orders], label_visibility="collapsed",
                                  format_func=lambda oid: next(f"{o.symbol} {o.side.value} {o.type.value} {o.qty:g} ({oid[:8]})" for o in orders if o.id == oid))
            if c2.button("Zrušit příkaz"):
                with guard():
                    order = next(o for o in orders if o.id == chosen)
                    broker.cancel_order(order.id, order.symbol)
                st.rerun()
        else:
            st.caption("Žádné otevřené příkazy.")

    account_section()
    st.divider()
    _order_ticket(broker)


def _order_ticket(broker) -> None:
    st.subheader("Nový příkaz")
    st.caption("Nech množství a stop na 0 – aplikace je dopočítá z ATR a z rizika na obchod. Nejdřív se zobrazí plán ke kontrole.")
    with st.form("ticket"):
        c1, c2, c3 = st.columns(3)
        symbol = c1.text_input("Symbol", value=_default_symbol()).strip().upper()
        side_label = c2.radio("Směr", ["Nákup", "Prodej"], horizontal=True)
        order_type = c3.radio("Typ", ["Tržní", "Limitní"], horizontal=True)
        c4, c5, c6, c7 = st.columns(4)
        qty = c4.number_input("Množství (0 = podle rizika)", value=0.0, min_value=0.0, step=1.0)
        limit = c5.number_input("Limitní cena", value=0.0, min_value=0.0, step=0.01, format="%.4f")
        stop = c6.number_input("Stop-loss (0 = z ATR)", value=0.0, min_value=0.0, step=0.01, format="%.4f")
        target = c7.number_input("Take-profit (0 = z ATR)", value=0.0, min_value=0.0, step=0.01, format="%.4f")
        planned = st.form_submit_button("Spočítat plán", type="primary")
    if planned:
        with guard():
            if order_type == "Limitní" and not limit:
                raise ValueError("Limitní příkaz potřebuje limitní cenu.")
            st.session_state["plan"] = {
                "plan": plan_order(
                    broker, get_provider(provider_name()), _risk(), symbol,
                    Side.BUY if side_label == "Nákup" else Side.SELL,
                    qty=qty or None, limit_price=limit if order_type == "Limitní" else None,
                    stop=stop or None, target=target or None, journal=get_journal(),
                ),
                "broker": broker_name(),
                "provider": provider_name(),
                "created": datetime.now(timezone.utc),
            }
    stored = st.session_state.get("plan")
    if stored is None:
        return
    if (stored["broker"], stored["provider"]) != (broker_name(), provider_name()):
        st.session_state.pop("plan", None)
        st.info("Broker nebo zdroj dat se změnil – spočítej plán znovu.")
        return
    age = datetime.now(timezone.utc) - stored["created"]
    if age > timedelta(minutes=5):
        st.session_state.pop("plan", None)
        st.info("Plán je starší než 5 minut a ceny se mezitím změnily – spočítej ho znovu.")
        return
    plan = stored["plan"]
    with st.container(border=True):
        st.markdown(f"**Plán příkazu** · spočítán v {stored['created'].astimezone():%H:%M:%S}")
        st.dataframe(pd.DataFrame(plan.summary_rows(), columns=["", "Hodnota"]), hide_index=True)
        for note in plan.notes:
            st.caption(note)
        for warning in plan.check.warnings:
            st.warning(warning)
        for reason in plan.check.reasons:
            st.error(reason)
        if not plan.check.allowed:
            return
        confirmed = st.checkbox("Rozumím riziku tohoto obchodu")
        if broker.is_live:
            confirmed = confirmed and st.text_input("Živý účet: pro potvrzení napiš ANO").strip().upper() == "ANO"
        if st.button("Odeslat příkaz", type="primary", disabled=not confirmed):
            with guard():
                order = execute_plan(broker, plan, get_journal(), source="dashboard")
            st.session_state.pop("plan", None)
            if order.status.is_open and order.type is OrderType.MARKET:
                st.toast("Trh je zavřený – příkaz se vyplní při otevření.", icon="⏳")
            else:
                st.toast(f"Příkaz odeslán: {order.status.value}", icon="✅")
            st.rerun()


# ---------------------------------------------------------------------------------------
# Bot
# ---------------------------------------------------------------------------------------
def bot_page() -> None:
    st.title("Obchodní bot")
    st.caption(
        "Bot každou svíčku vyhodnotí strategii a obchoduje podle stejných pravidel jako backtest: vstup jen na nový signál, "
        "stop-loss a take-profit z ATR, limity rizika, uzavření pozic před koncem seance."
    )
    runner = bot_runner()
    cfg = settings()
    if runner.running:
        st.success(f"Bot běží od {runner.started_at:%H:%M:%S}: {runner.label}", icon="🤖")
        if st.button("Zastavit bota", type="primary"):
            runner.stop()
            st.rerun()
    else:
        with st.form("bot"):
            c1, c2 = st.columns([3, 1])
            symbols_text = c1.text_input("Symboly", value=", ".join(cfg.watchlist_symbols[:4]))
            interval = c2.selectbox("Interval", ["1m", "5m", "15m", "30m", "1h"], index=1)
            strategy_key = st.selectbox("Strategie", list(STRATEGIES), format_func=lambda k: STRATEGIES[k].name,
                                        index=list(STRATEGIES).index("vwap_trend"))
            dry_run = st.toggle("Suchý běh (jen vypisovat rozhodnutí, neposílat příkazy)", value=True)
            start = st.form_submit_button("Spustit bota", type="primary")
        st.caption(f"Broker: **{broker_name()}** · zdroj dat: **{provider_name()}** · parametry strategie jsou výchozí.")
        if start:
            with guard():
                provider = create_provider(provider_name(), cfg)
                broker = create_broker(broker_name(), cfg, provider=provider)
                if broker.is_live and not dry_run:
                    raise ValueError("Živého bota spouštěj z příkazové řádky (daytrader bot), kde se potvrzuje ručně.")
                symbols = parse_symbols(symbols_text)
                strategy = get_strategy(strategy_key)
                bot = TradingBot(broker, provider, strategy, _risk(), Journal(cfg.ensure_data_dir() / "journal.db"),
                                 BotConfig(symbols=symbols, interval=interval, dry_run=dry_run))
                runner.start(bot, f"{strategy.label()} · {', '.join(symbols)} · {interval}{' · suchý běh' if dry_run else ''}")
            st.rerun()
    if runner.last_error:
        st.error(runner.last_error)

    @st.fragment(run_every="15s")
    def decisions() -> None:
        st.subheader("Rozhodnutí bota")
        if runner.decisions:
            frame = pd.DataFrame(
                [(ts.strftime("%H:%M:%S"), d.symbol, d.action, d.message) for ts, d in runner.decisions],
                columns=["Čas", "Symbol", "Akce", "Zpráva"],
            )
            st.dataframe(frame, hide_index=True)
        else:
            st.caption("Zatím žádná rozhodnutí (bot vypisuje jen vstupy, výstupy, blokace a chyby).")

    decisions()
    st.info("Bot běží jen dokud běží tento dashboard. Pro dlouhodobý běh použij příkaz `daytrader bot` v terminálu.", icon="ℹ️")


# ---------------------------------------------------------------------------------------
# Journal
# ---------------------------------------------------------------------------------------
def journal_page() -> None:
    st.title("Deník obchodů")
    days = st.slider("Období (dní)", 1, 365, 30)
    with guard():
        broker = get_broker(broker_name(), provider_name())
        fills = broker.get_fills(datetime.now(timezone.utc) - timedelta(days=days))
    trips = round_trips(fills)
    stats = journal_stats(trips)
    cols = st.columns(5)
    cols[0].metric("Obchodů", stats.get("trades", 0), border=True)
    cols[1].metric("Čistý P/L", fmt(stats.get("net_pnl")), border=True)
    cols[2].metric("Úspěšnost", format_metric("win_rate_pct", stats.get("win_rate_pct")), border=True)
    cols[3].metric("Profit factor", format_metric("profit_factor", stats.get("profit_factor")), border=True)
    cols[4].metric("Průměr na obchod", fmt(stats.get("expectancy")), border=True)
    if trips.empty:
        st.info("Zatím žádné uzavřené obchody. Zkus papírový účet na stránce Obchodování nebo spusť bota.")
    else:
        daily = daily_pnl(trips, tz="Europe/Prague")
        left, right = st.columns(2)
        with left:
            st.markdown("**P/L za den**")
            _plotly(charts.pnl_bars(daily, theme_mode()))
        with right:
            st.markdown("**Kumulativní P/L**")
            _plotly(charts.cumulative_chart(daily.cumsum(), theme_mode()))
        view = trips.copy()
        view["entry_time"] = local_time(view["entry_time"])
        view["exit_time"] = local_time(view["exit_time"])
        view = view.rename(columns={
            "symbol": "Symbol", "side": "Směr", "entry_time": "Vstup", "exit_time": "Výstup", "qty": "Množství",
            "entry_price": "Cena vstupu", "exit_price": "Cena výstupu", "pnl": "P/L", "pnl_pct": "P/L %", "commission": "Poplatky",
        })
        st.dataframe(view.iloc[::-1], hide_index=True, column_config={
            c: st.column_config.NumberColumn(format="%.2f") for c in ("Cena vstupu", "Cena výstupu", "P/L", "P/L %", "Poplatky")
        })
        st.download_button("Stáhnout obchody (CSV)", trips.to_csv(index=False).encode("utf-8"), file_name="obchody.csv",
                           mime="text/csv", help="Hodí se i jako podklad pro daňové přiznání.")
        with st.expander("Všechny statistiky"):
            st.dataframe(pd.DataFrame([(METRIC_LABELS.get(k, k), format_metric(k, v)) for k, v in stats.items()],
                                      columns=["Metrika", "Hodnota"]), hide_index=True)
    journal = get_journal()
    st.subheader("Události bota a příkazy")
    tab_events, tab_orders = st.tabs(["Události", "Odeslané příkazy"])
    with tab_events:
        events = journal.events(200)
        if not events.empty:
            events["ts"] = local_time(events["ts"])
        st.dataframe(events.drop(columns=["id"]).rename(columns={
            "ts": "Čas", "level": "Úroveň", "source": "Zdroj", "symbol": "Symbol", "message": "Zpráva"}), hide_index=True)
    with tab_orders:
        orders = journal.orders(200)
        if not orders.empty:
            orders["ts"] = local_time(orders["ts"])
            orders = orders.drop(columns=["id"]).rename(columns={
                "ts": "Čas", "broker": "Broker", "order_id": "ID příkazu", "symbol": "Symbol", "side": "Strana",
                "qty": "Množství", "type": "Typ", "price": "Cena", "stop_loss": "Stop-loss", "take_profit": "Take-profit",
                "strategy": "Strategie", "reason": "Důvod", "status": "Stav"})
        st.dataframe(orders, hide_index=True)


# ---------------------------------------------------------------------------------------
# Settings / help
# ---------------------------------------------------------------------------------------
def settings_page() -> None:
    st.title("Nastavení a nápověda")
    cfg = settings()
    st.dataframe(pd.DataFrame(cfg.masked_summary().items(), columns=["Nastavení", "Hodnota"]), hide_index=True)
    st.markdown(
        """
Nastavení se mění v souboru **`.env`** ve složce, ze které aplikaci spouštíš (vzor je v `.env.example`).
Po změně dashboard restartuj.

**Doporučený postup pro začátečníka**
1. Projdi si grafy a technický přehled na stránce *Analýza* (klidně s demo daty).
2. Na stránce *Backtest* otestuj strategie na několika symbolech a delším období. Sleduj max. propad a počet obchodů, nejen výnos.
3. Obchoduj **alespoň několik týdnů na papírovém účtu** a veď si deník.
4. Teprve pak zvaž malý živý účet – riziko na obchod drž kolem 1 % kapitálu.

**Napojení na API**
- *Yahoo Finance* – zdarma, bez klíče (akcie z celého světa, pražská burza s příponou `.PR`).
- *Alpaca* – papírový účet zdarma na [alpaca.markets](https://alpaca.markets), klíče do `.env`.
- *Kryptoburzy* – přes CCXT (Binance, Kraken, Coinbase, Coinmate…), nejdřív testnet.
- *Claude API* – volitelný AI komentář, placený podle spotřeby ([console.anthropic.com](https://console.anthropic.com)).
"""
    )
    st.subheader("Papírový účet")
    broker = get_broker("paper", provider_name())
    if isinstance(broker, PaperBroker):
        st.caption(f"Databáze: {broker.db_path}")
        cash = st.number_input("Počáteční kapitál", value=float(cfg.paper_starting_cash), min_value=100.0, step=1000.0)
        sure = st.checkbox("Opravdu smazat všechny papírové pozice, příkazy a obchody")
        if st.button("Vynulovat papírový účet", disabled=not sure):
            broker.reset(cash)
            st.success("Papírový účet byl vynulován.")
