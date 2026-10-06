"""Command line interface: ``daytrader --help``."""

from __future__ import annotations

import functools
import math
import subprocess
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Annotated, Any, Callable

import pandas as pd
import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from . import DISCLAIMER, __version__
from .ai import AIAnalyst, AIError
from .analysis.snapshot import build_snapshot
from .backtest import EXIT_REASONS, BacktestConfig, grid_search, run_backtest
from .backtest.metrics import METRIC_LABELS, format_metric
from .bot import BotAlreadyRunning, BotConfig, TradingBot, next_market_open, symbols_label
from .brokers import BrokerError, create_broker
from .brokers.base import Broker
from .brokers.paper import PaperBroker
from .config import ConfigError, Settings, get_settings, parse_symbols
from .data import DataError, DataProvider, create_provider
from .journal import Journal, journal_stats, round_trips
from .models import Side
from .risk import RiskConfig, RiskManager
from .scanner import scan as run_scan
from .strategies import STRATEGIES, get_strategy
from .timeframes import interval_seconds
from .trading import OrderPlan, execute_plan, plan_order


def ensure_utf8_output() -> None:
    """Czech text must not crash when stdout uses a legacy Windows code page (pipes, Git Bash, CI)."""
    for stream in (sys.stdout, sys.stderr):
        encoding = (getattr(stream, "encoding", None) or "").lower().replace("-", "")
        if encoding != "utf8" and hasattr(stream, "reconfigure"):
            try:
                stream.reconfigure(encoding="utf-8", errors="replace")
            except (ValueError, OSError):
                pass


ensure_utf8_output()

app = typer.Typer(
    help="Day trading nástroj: analýzy, scanner, backtesty a obchodování (papírové i přes API).",
    no_args_is_help=True,
    add_completion=False,
    rich_markup_mode="rich",
)
console = Console()

ProviderOpt = Annotated[str | None, typer.Option("--provider", "-d", help="Zdroj dat: yahoo | alpaca | ccxt | demo")]
BrokerOpt = Annotated[str | None, typer.Option("--broker", "-b", help="Broker: paper | alpaca | ccxt")]
IntervalOpt = Annotated[str, typer.Option("--interval", "-i", help="Interval svíček: 1m, 5m, 15m, 30m, 1h, 1d")]
PeriodOpt = Annotated[str, typer.Option("--period", "-p", help="Období dat: 1d, 5d, 1mo, 3mo, 6mo, 1y")]
YesOpt = Annotated[bool, typer.Option("--yes", "-y", help="Nepožadovat potvrzení (jen papírový/testovací účet)")]


# ---------------------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------------------
def guarded(fn: Callable[..., Any]) -> Callable[..., Any]:
    @functools.wraps(fn)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        try:
            return fn(*args, **kwargs)
        except (ConfigError, DataError, BrokerError, AIError, BotAlreadyRunning, ValueError) as exc:
            console.print(f"[bold red]Chyba:[/] {exc}")
            raise typer.Exit(1) from exc

    return wrapper


def fmt(value: Any, digits: int = 2, suffix: str = "") -> str:
    if value is None or (isinstance(value, float) and not math.isfinite(value)):
        return "—"
    if isinstance(value, (int, float)):
        return f"{value:,.{digits}f}".replace(",", " ") + suffix
    return str(value)


def local(ts: Any) -> pd.Timestamp:
    """Timestamp in the computer's local timezone (fills and orders are stored in UTC)."""
    stamp = pd.Timestamp(ts)
    if stamp.tzinfo is None:
        stamp = stamp.tz_localize("UTC")
    return stamp.tz_convert(datetime.now().astimezone().tzinfo)


def colored(value: float | None, digits: int = 2, suffix: str = " %") -> str:
    if value is None or not math.isfinite(value):
        return "—"
    color = "blue" if value > 0 else "dark_orange" if value < 0 else "white"
    return f"[{color}]{value:+.{digits}f}{suffix}[/]"


def parse_params(values: list[str] | None) -> dict[str, str]:
    params: dict[str, str] = {}
    for item in values or []:
        if "=" not in item:
            raise ValueError(f"Parametr '{item}' musí mít tvar klic=hodnota.")
        key, value = item.split("=", 1)
        params[key.strip()] = value.strip()
    return params


def _number(text: str) -> int | float | str:
    for cast in (int, float):
        try:
            return cast(text)
        except ValueError:
            pass
    return text


def parse_grid(values: list[str]) -> dict[str, list[Any]]:
    grid = {}
    for key, value in parse_params(values).items():
        grid[key] = [_number(v.strip()) for v in value.split(",") if v.strip()]
    return grid


def journal_for() -> Journal:
    return Journal(get_settings().ensure_data_dir() / "journal.db")


def risk_manager(
    max_trades: int | None = None, max_positions: int | None = None, settings: Settings | None = None
) -> RiskManager:
    config = RiskConfig.from_settings(settings or get_settings())
    if max_trades is not None:
        config.max_trades_per_day = max_trades
    if max_positions is not None:
        config = config.with_max_positions(max_positions)
    return RiskManager(config)


def make_broker(
    broker: str | None, provider: str | None, settings: Settings | None = None
) -> tuple[Broker, DataProvider]:
    settings = settings or get_settings()
    data = create_provider(provider, settings)
    return create_broker(broker, settings, provider=data), data


def confirm_live(broker: Broker, yes: bool, what: str) -> None:
    if broker.is_live:
        console.print(Panel(f"[bold red]POZOR: ŽIVÝ ÚČET – {what} použije skutečné peníze.[/]", border_style="red"))
        answer = typer.prompt("Pro potvrzení napiš ANO")
        if answer.strip().upper() != "ANO":
            console.print("Zrušeno.")
            raise typer.Exit(0)
    elif not yes and not typer.confirm(f"Provést: {what}?", default=True):
        console.print("Zrušeno.")
        raise typer.Exit(0)


def kv_table(rows: list[tuple[str, str]], title: str | None = None) -> Table:
    table = Table(title=title, show_header=False, box=None, pad_edge=False)
    table.add_column(style="bold")
    table.add_column()
    for key, value in rows:
        table.add_row(key, value)
    return table


# ---------------------------------------------------------------------------------------
# general
# ---------------------------------------------------------------------------------------
@app.command()
def info() -> None:
    """Zobrazí aktuální nastavení (bez tajných klíčů)."""
    settings = get_settings()
    console.print(kv_table(list(settings.masked_summary().items()), title=f"daytrader {__version__}"))
    console.print(Panel(DISCLAIMER, border_style="yellow"))


@app.command()
@guarded
def quote(symbols: Annotated[list[str], typer.Argument(help="Symboly, např. AAPL CEZ.PR BTC-USD")], provider: ProviderOpt = None) -> None:
    """Aktuální cena a denní změna."""
    data = create_provider(provider, get_settings())
    table = Table("Symbol", "Cena", "Změna", "Denní min", "Denní max")
    for symbol in symbols:
        try:
            q = data.get_quote(symbol.upper())
        except DataError as exc:
            table.add_row(symbol.upper(), f"[red]{exc}[/]", "", "", "")
            continue
        table.add_row(q.symbol, fmt(q.price, 2), colored(q.change_pct), fmt(q.day_low), fmt(q.day_high))
    console.print(table)


@app.command()
@guarded
def analyze(
    symbol: Annotated[str, typer.Argument(help="Symbol, např. AAPL")],
    interval: IntervalOpt = "5m",
    period: PeriodOpt = "5d",
    provider: ProviderOpt = None,
    ai: Annotated[bool, typer.Option("--ai", help="Přidat AI komentář (Claude API, placené)")] = False,
    question: Annotated[str | None, typer.Option("--question", "-q", help="Otázka pro AI analytika")] = None,
) -> None:
    """Technická analýza: trend, momentum, VWAP, volatilita, důležité úrovně."""
    settings = get_settings()
    data = create_provider(provider, settings)
    symbol = symbol.upper()
    bars = data.get_bars(symbol, interval=interval, period=period)
    snap = build_snapshot(bars, symbol, interval, stop_atr_mult=settings.stop_atr_mult)
    bias_color = {"býčí": "blue", "medvědí": "dark_orange"}.get(snap.bias, "white")
    head = [
        ("Cena", fmt(snap.price)),
        ("Změna", colored(snap.change_pct)),
        ("Trend", snap.trend),
        ("Skóre", f"[{bias_color}]{snap.score:+d} ({snap.bias})[/]"),
        ("RSI", fmt(snap.rsi, 1)),
        ("ATR", f"{fmt(snap.atr)} ({fmt(snap.atr_pct)} %)"),
        ("VWAP", fmt(snap.vwap)),
        ("Rel. objem", fmt(snap.rvol, 2, "×")),
        ("ADX", fmt(snap.adx, 1)),
    ]
    console.print(Panel(kv_table(head), title=f"{symbol} · {interval} · {snap.timestamp[:16]}", border_style=bias_color))
    console.print("[bold]Signály[/]")
    for line in snap.signals:
        console.print(f"  • {line}")
    if snap.levels:
        names = {
            "prev_high": "Včerejší max", "prev_low": "Včerejší min", "prev_close": "Včerejší close",
            "today_open": "Dnešní open", "today_high": "Dnešní max", "today_low": "Dnešní min",
            "pivot_R2": "Pivot R2", "pivot_R1": "Pivot R1", "pivot_P": "Pivot P",
            "pivot_S1": "Pivot S1", "pivot_S2": "Pivot S2",
        }
        rows = [(label, fmt(snap.levels[key])) for key, label in names.items() if key in snap.levels]
        console.print(kv_table(rows, title="Úrovně"))
    if snap.swing.get("resistance") or snap.swing.get("support"):
        console.print(
            f"Rezistence: {', '.join(fmt(x) for x in snap.swing.get('resistance', [])) or '—'} | "
            f"Supporty: {', '.join(fmt(x) for x in snap.swing.get('support', [])) or '—'}"
        )
    if ai:
        if not settings.has_ai:
            raise ConfigError("Pro AI komentář nastav ANTHROPIC_API_KEY v souboru .env (placená služba).")
        analyst = AIAnalyst(settings.anthropic_api_key.get_secret_value(), settings.ai_model, settings.ai_effort)
        with console.status("AI analytik přemýšlí…"):
            result = analyst.analyze(snap.to_dict(), data.get_news(symbol, 8), question)
        cost = result.estimated_cost_usd
        footer = f"{result.model} · {result.input_tokens}+{result.output_tokens} tokenů" + (
            f" · cca ${cost:.3f}" if cost is not None else ""
        )
        console.print(Panel(result.text, title="AI komentář (není investiční doporučení)", subtitle=footer))


@app.command()
@guarded
def scan(
    symbols: Annotated[list[str] | None, typer.Argument(help="Symboly (výchozí = DT_WATCHLIST)")] = None,
    interval: IntervalOpt = "5m",
    period: PeriodOpt = "5d",
    provider: ProviderOpt = None,
    strategy: Annotated[str | None, typer.Option("--strategy", "-s", help="Ukázat i signál strategie")] = None,
) -> None:
    """Scanner watchlistu seřazený podle síly technického signálu."""
    settings = get_settings()
    data = create_provider(provider, settings)
    symbols = parse_symbols(",".join(symbols)) if symbols else settings.watchlist_symbols
    strat = get_strategy(strategy) if strategy else None
    with console.status(f"Skenuji {len(symbols)} symbolů…"):
        frame = run_scan(symbols, data, interval, period, strat)
    table = Table("Symbol", "Cena", "Změna", "Gap", "RVOL", "RSI", "ATR %", "vs VWAP", "Trend", "Skóre", *(["Signál"] if strat else []))
    for row in frame.itertuples():
        if isinstance(row.error, str) and row.error:
            table.add_row(row.symbol, f"[red]{row.error[:60]}[/]")
            continue
        cells = [
            row.symbol, fmt(row.price), colored(row.change_pct), colored(row.gap_pct), fmt(row.rvol, 2, "×"),
            fmt(row.rsi, 0), fmt(row.atr_pct), colored(row.vs_vwap_pct), row.trend, f"{int(row.score):+d} {row.bias}",
        ]
        if strat:
            cells.append({1: "[blue]LONG[/]", -1: "[dark_orange]SHORT[/]"}.get(row.signal, "—"))
        table.add_row(*cells)
    console.print(table)


@app.command()
def strategies() -> None:
    """Seznam strategií a jejich parametrů."""
    for cls in STRATEGIES.values():
        params = ", ".join(f"{p.name}={p.default}" for p in cls.params_spec)
        console.print(f"[bold]{cls.key}[/] – {cls.name}{' [dim](jen intradenní)[/]' if cls.intraday_only else ''}")
        console.print(f"   {cls.description}")
        console.print(f"   [dim]parametry: {params}[/]")


@app.command()
@guarded
def backtest(
    symbol: Annotated[str, typer.Argument(help="Symbol")],
    strategy: Annotated[str, typer.Option("--strategy", "-s", help="Klíč strategie (viz `daytrader strategies`)")] = "ema_cross",
    param: Annotated[list[str] | None, typer.Option("--param", help="Parametr strategie klic=hodnota (lze opakovat)")] = None,
    interval: IntervalOpt = "5m",
    period: PeriodOpt = "1mo",
    provider: ProviderOpt = None,
    capital: Annotated[float | None, typer.Option(help="Počáteční kapitál [výchozí DT_PAPER_STARTING_CASH]")] = None,
    risk: Annotated[float | None, typer.Option(help="Riziko na obchod v % kapitálu [DT_RISK_PER_TRADE_PCT]")] = None,
    max_position: Annotated[float | None, typer.Option(help="Max. pozice v % kapitálu [DT_MAX_POSITION_PCT]")] = None,
    stop_atr: Annotated[float | None, typer.Option(help="Stop-loss v násobcích ATR, 0 = bez stopu [DT_STOP_ATR_MULT]")] = None,
    tp_r: Annotated[float | None, typer.Option(help="Take-profit v násobcích rizika R, 0 = bez cíle [DT_TAKE_PROFIT_R]")] = None,
    commission_share: Annotated[float | None, typer.Option(help="Poplatek za kus")] = None,
    commission_pct: Annotated[float | None, typer.Option(help="Poplatek v % z objemu")] = None,
    slippage: Annotated[float | None, typer.Option(help="Skluz v bazických bodech (1 bp = 0,01 %)")] = None,
    short: Annotated[bool | None, typer.Option("--short/--no-short", help="Povolit short [DT_ALLOW_SHORT]")] = None,
    eod: Annotated[bool, typer.Option("--eod/--no-eod", help="Zavírat pozice na konci dne")] = True,
    trades: Annotated[int, typer.Option(help="Kolik posledních obchodů vypsat")] = 10,
    export: Annotated[Path | None, typer.Option(help="Uložit obchody do CSV")] = None,
) -> None:
    """Backtest strategie na historických datech."""
    data = create_provider(provider, get_settings())
    symbol = symbol.upper()
    strat = get_strategy(strategy, **parse_params(param))
    with console.status("Stahuji data…"):
        bars = data.get_bars(symbol, interval=interval, period=period)
    config = BacktestConfig.from_settings(
        get_settings(), symbol, initial_capital=capital, risk_per_trade_pct=risk, max_position_pct=max_position,
        stop_atr_mult=stop_atr, take_profit_r=tp_r, commission_per_share=commission_share,
        commission_pct=commission_pct, slippage_bps=slippage, allow_short=short, eod_flatten=eod,
    )
    result = run_backtest(bars, strat, config, symbol=symbol, interval=interval)
    console.print(
        Panel(
            kv_table(result.summary()),
            title=f"Backtest {symbol} · {strat.label()} · {interval} · {bars.index[0]:%Y-%m-%d} – {bars.index[-1]:%Y-%m-%d}",
        )
    )
    frame = result.trades_df()
    if not frame.empty and trades > 0:
        table = Table("Vstup", "Výstup", "Směr", "Ks", "Cena vstupu", "Cena výstupu", "P/L", "R", "Důvod")
        for row in frame.tail(trades).itertuples():
            table.add_row(
                f"{row.entry_time:%m-%d %H:%M}", f"{row.exit_time:%m-%d %H:%M}", row.side, fmt(row.qty, 4 if config.fractional else 0),
                fmt(row.entry_price), fmt(row.exit_price), colored(row.pnl, 2, ""), fmt(row.r_multiple),
                EXIT_REASONS.get(row.exit_reason, row.exit_reason),
            )
        console.print(table)
    if export:
        frame.to_csv(export, index=False)
        console.print(f"Obchody uloženy do {export}")
    console.print(
        "[dim]Backtest není zárukou budoucích výsledků. Pozor na přeoptimalizování a počítej s poplatky a skluzem.[/]"
    )


@app.command()
@guarded
def optimize(
    symbol: Annotated[str, typer.Argument(help="Symbol")],
    strategy: Annotated[str, typer.Option("--strategy", "-s")] = "ema_cross",
    grid: Annotated[list[str] | None, typer.Option("--grid", "-g", help="Mřížka parametru, např. fast=5,9,12 (lze opakovat)")] = None,
    interval: IntervalOpt = "5m",
    period: PeriodOpt = "1mo",
    provider: ProviderOpt = None,
    holdout: Annotated[float, typer.Option(help="Podíl dat odložených pro ověření (out-of-sample)")] = 0.3,
    sort: Annotated[str, typer.Option(help="Řadit podle metriky")] = "total_return_pct",
    top: Annotated[int, typer.Option(help="Počet nejlepších výsledků")] = 10,
) -> None:
    """Hledání parametrů s ověřením na odložených datech (ochrana proti přeoptimalizování)."""
    if not grid:
        raise ValueError("Zadej aspoň jednu mřížku, např. --grid fast=5,9,12 --grid slow=21,30.")
    data = create_provider(provider, get_settings())
    symbol = symbol.upper()
    bars = data.get_bars(symbol, interval=interval, period=period)
    days = pd.Index(bars.index.date).unique()
    split_at = int(len(days) * (1 - holdout)) if 0 < holdout < 1 else len(days)
    if split_at < 2:
        raise ValueError("Na rozdělení je málo dní – prodluž období.")
    in_sample = bars[pd.Index(bars.index.date).isin(days[:split_at])]
    out_sample = bars[pd.Index(bars.index.date).isin(days[split_at:])]
    config = BacktestConfig.from_settings(get_settings(), symbol)
    with console.status("Počítám kombinace…"):
        results = grid_search(in_sample, strategy, parse_grid(grid), config, interval=interval, sort_by=sort)
    if results.empty:
        raise ValueError("Žádná platná kombinace parametrů.")
    table = Table(*results.columns)
    for row in results.head(top).itertuples(index=False):
        table.add_row(*(fmt(v) if isinstance(v, float) else str(v) for v in row))
    console.print(table)
    best = {k: results.iloc[0][k] for k in parse_grid(grid)}
    if not out_sample.empty:
        test = run_backtest(out_sample, get_strategy(strategy, **best), config, symbol=symbol, interval=interval)
        rows = [(METRIC_LABELS[k], format_metric(k, test.metrics.get(k))) for k in
                ("total_return_pct", "max_drawdown_pct", "sharpe", "profit_factor", "win_rate_pct", "trades")]
        console.print(Panel(kv_table(rows), title=f"Ověření nejlepších parametrů {best} na odložených datech"))
        console.print("[dim]Pokud výsledky na odložených datech výrazně zaostávají, parametry jsou přeoptimalizované.[/]")


# ---------------------------------------------------------------------------------------
# trading
# ---------------------------------------------------------------------------------------
@app.command()
@guarded
def account(broker: BrokerOpt = None, provider: ProviderOpt = None) -> None:
    """Stav účtu a otevřené pozice."""
    brk, _ = make_broker(broker, provider)
    brk.sync()
    acct = brk.get_account()
    rows = [
        ("Broker", f"{brk.name} ({'LIVE' if brk.is_live else 'paper/test'})"),
        ("Kapitál", f"{fmt(acct.equity)} {acct.currency}"),
        ("Hotovost", fmt(acct.cash)),
        ("Kupní síla", fmt(acct.buying_power)),
        ("Dnešní P/L", colored(acct.day_pnl, 2, f" {acct.currency}") if acct.day_pnl is not None else "—"),
    ]
    if acct.day_trade_count is not None:
        rows.append(("Day trady (5 dní)", str(acct.day_trade_count)))
    console.print(kv_table(rows, title="Účet"))
    positions(broker=broker, provider=provider)


@app.command()
@guarded
def positions(broker: BrokerOpt = None, provider: ProviderOpt = None) -> None:
    """Otevřené pozice."""
    brk, _ = make_broker(broker, provider)
    items = brk.get_positions()
    if not items:
        console.print("Žádné otevřené pozice.")
        return
    table = Table("Symbol", "Směr", "Množství", "Prům. cena", "Aktuální", "Hodnota", "P/L", "P/L %")
    for p in items:
        table.add_row(p.symbol, p.side, fmt(abs(p.qty), 4), fmt(p.avg_price), fmt(p.current_price), fmt(p.market_value),
                      colored(p.unrealized_pnl, 2, ""), colored(p.unrealized_pnl_pct))
    console.print(table)


@app.command()
@guarded
def orders(
    broker: BrokerOpt = None,
    provider: ProviderOpt = None,
    all_: Annotated[bool, typer.Option("--all", help="I uzavřené příkazy")] = False,
) -> None:
    """Příkazy u brokera."""
    brk, _ = make_broker(broker, provider)
    brk.sync()
    items = brk.get_orders("all" if all_ else "open", limit=50)
    if not items:
        console.print("Žádné příkazy.")
        return
    table = Table("ID", "Čas", "Symbol", "Strana", "Typ", "Ks", "Limit", "Stop", "Stav", "Vyplněno @")
    for o in items:
        table.add_row(o.id[:12], f"{local(o.created_at):%m-%d %H:%M}" if o.created_at else "", o.symbol, o.side.value, o.type.value,
                      fmt(o.qty, 4), fmt(o.limit_price), fmt(o.stop_price), o.status.value, fmt(o.filled_avg_price))
    console.print(table)


def _print_plan(plan: OrderPlan) -> None:
    console.print(kv_table(plan.summary_rows(), title="Plán příkazu"))
    for note in plan.notes:
        console.print(f"[dim]• {note}[/]")
    for warning in plan.check.warnings:
        console.print(f"[yellow]⚠ {warning}[/]")
    for reason in plan.check.reasons:
        console.print(f"[red]✗ {reason}[/]")


def _order_command(side: Side, symbol, qty, limit, stop, tp, auto, broker, provider, yes) -> None:
    brk, data = make_broker(broker, provider)
    journal = journal_for()
    plan = plan_order(brk, data, risk_manager(), symbol, side, qty, limit, stop, tp, auto, journal)
    _print_plan(plan)
    if not plan.check.allowed:
        raise typer.Exit(1)
    confirm_live(brk, yes, f"{'nákup' if side is Side.BUY else 'prodej'} {plan.qty:g} {plan.symbol}")
    order = execute_plan(brk, plan, journal)
    console.print(f"[green]Příkaz odeslán[/]: {order.id} · stav {order.status.value}"
                  + (f" · vyplněno @ {fmt(order.filled_avg_price)}" if order.filled_avg_price else ""))
    if order.status.is_open and order.type.value == "market":
        console.print("[yellow]Trh je teď zavřený – příkaz čeká a vyplní se při otevření trhu.[/]")


QtyOpt = Annotated[float | None, typer.Option("--qty", "-n", help="Množství (jinak se dopočítá z rizika)")]
LimitOpt = Annotated[float | None, typer.Option("--limit", help="Limitní cena (jinak tržní příkaz)")]
StopOpt = Annotated[float | None, typer.Option("--stop", help="Stop-loss")]
TpOpt = Annotated[float | None, typer.Option("--tp", help="Take-profit")]
AutoOpt = Annotated[bool, typer.Option("--auto-levels/--no-auto-levels", help="Dopočítat stop/target z ATR")]


@app.command()
@guarded
def buy(symbol: str, qty: QtyOpt = None, limit: LimitOpt = None, stop: StopOpt = None, tp: TpOpt = None,
        auto: AutoOpt = True, broker: BrokerOpt = None, provider: ProviderOpt = None, yes: YesOpt = False) -> None:
    """Nákup (long nebo uzavření shortu) s kontrolou rizika."""
    _order_command(Side.BUY, symbol, qty, limit, stop, tp, auto, broker, provider, yes)


@app.command()
@guarded
def sell(symbol: str, qty: QtyOpt = None, limit: LimitOpt = None, stop: StopOpt = None, tp: TpOpt = None,
         auto: AutoOpt = True, broker: BrokerOpt = None, provider: ProviderOpt = None, yes: YesOpt = False) -> None:
    """Prodej (uzavření longu nebo short) s kontrolou rizika."""
    _order_command(Side.SELL, symbol, qty, limit, stop, tp, auto, broker, provider, yes)


@app.command()
@guarded
def close(symbol: str, broker: BrokerOpt = None, provider: ProviderOpt = None, yes: YesOpt = False) -> None:
    """Uzavře pozici v symbolu (a zruší jeho otevřené příkazy)."""
    brk, _ = make_broker(broker, provider)
    confirm_live(brk, yes, f"uzavření pozice {symbol.upper()}")
    order = brk.close_position(symbol.upper())
    console.print("Pozice neexistuje." if order is None else f"[green]Uzavírací příkaz[/] {order.id} · {order.status.value}")


@app.command("close-all")
@guarded
def close_all(broker: BrokerOpt = None, provider: ProviderOpt = None, yes: YesOpt = False) -> None:
    """Uzavře všechny pozice."""
    brk, _ = make_broker(broker, provider)
    confirm_live(brk, yes, "uzavření VŠECH pozic")
    closed = brk.close_all()
    console.print(f"Uzavírací příkazy: {len(closed)}")


@app.command()
@guarded
def cancel(order_id: str, broker: BrokerOpt = None, provider: ProviderOpt = None) -> None:
    """Zruší otevřený příkaz."""
    brk, _ = make_broker(broker, provider)
    match = next((o for o in brk.get_orders("open") if o.id.startswith(order_id)), None)
    if match is None:
        raise BrokerError(f"Otevřený příkaz {order_id} nenalezen.")
    brk.cancel_order(match.id, match.symbol)
    console.print(f"Příkaz {match.id} zrušen.")


@app.command("paper-reset")
@guarded
def paper_reset(
    cash: Annotated[float | None, typer.Option(help="Nový počáteční kapitál")] = None,
    provider: ProviderOpt = None,
    yes: YesOpt = False,
) -> None:
    """Vynuluje papírový účet."""
    brk, _ = make_broker("paper", provider)
    assert isinstance(brk, PaperBroker)
    if not yes and not typer.confirm("Smazat všechny papírové pozice, příkazy a obchody?", default=False):
        raise typer.Exit(0)
    brk.reset(cash)
    console.print(f"Papírový účet vynulován ({fmt(cash or brk.starting_cash)}).")


@app.command()
@guarded
def bot(
    strategy: Annotated[str | None, typer.Option("--strategy", "-s", help="Strategie [DT_BOT_STRATEGY]")] = None,
    symbols: Annotated[str | None, typer.Option(help="Symboly oddělené čárkou [DT_BOT_SYMBOLS, jinak DT_WATCHLIST]")] = None,
    param: Annotated[list[str] | None, typer.Option("--param", help="Parametr strategie klic=hodnota [DT_BOT_PARAMS]")] = None,
    interval: Annotated[str | None, typer.Option("--interval", "-i", help="Interval svíček [DT_BOT_INTERVAL]")] = None,
    lookback: Annotated[str, typer.Option(help="Kolik historie načítat pro signály")] = "5d",
    max_trades: Annotated[int | None, typer.Option("--max-trades", min=1, help="Max. obchodů za den [DT_MAX_TRADES_PER_DAY]")] = None,
    max_positions: Annotated[int | None, typer.Option(
        "--max-positions", min=1, help="Max. pozic najednou; každá se zmenší, aby se všechny vešly do kapitálu "
        "[DT_MAX_OPEN_POSITIONS]")] = None,
    short: Annotated[bool | None, typer.Option("--short/--no-short", help="Povolit sázky na pokles [DT_ALLOW_SHORT]")] = None,
    broker: BrokerOpt = None,
    provider: ProviderOpt = None,
    once: Annotated[bool, typer.Option("--once", help="Jen jedno vyhodnocení a konec")] = False,
    dry_run: Annotated[bool, typer.Option("--dry-run", help="Jen vypisovat rozhodnutí, nic neposílat")] = False,
    yes: YesOpt = False,
) -> None:
    """Automatický obchodní bot (Ctrl+C = zastavení). Výchozí nastavení bere z .env (DT_BOT_*).

    Symboly mohou být i celé skupiny: @us, @etf, @krypto, @binance, @praha, @dax, @londyn."""
    settings = get_settings()
    if short is not None:
        settings = settings.model_copy(update={"allow_short": short})
    brk, data = make_broker(broker, provider, settings)
    strategy_key = strategy or settings.bot_strategy
    if param:
        params: dict[str, Any] = parse_params(param)
    elif strategy_key == settings.bot_strategy:
        params = settings.bot_param_dict
    else:
        params = {}
    strat = get_strategy(strategy_key, **params)
    watch = parse_symbols(symbols) if symbols else settings.bot_symbol_list
    interval = interval or settings.bot_interval
    if not dry_run:
        confirm_live(brk, yes, f"spuštění bota {strat.label()} na {symbols_label(watch)}")
    risk = risk_manager(max_trades, max_positions, settings)
    trading_bot = TradingBot(brk, data, strat, risk, journal_for(),
                             BotConfig(symbols=watch, interval=interval, lookback=lookback, dry_run=dry_run))
    last_notice = {"at": float("-inf")}

    def show(decisions) -> None:
        stamp = datetime.now().strftime("%H:%M:%S")
        shown = [d for d in decisions if once or d.action not in ("hold", "skip")]
        for d in shown:
            color = {"error": "red", "blocked": "yellow", "enter_long": "blue", "enter_short": "dark_orange"}.get(d.action, "white")
            console.print(f"[dim]{stamp}[/] [bold]{d.symbol:10}[/] [{color}]{d.action:12}[/] {d.message}")
            for warning in d.warnings:
                console.print(f"           [yellow]⚠ {warning}[/]")
        if shown:
            last_notice["at"] = time.monotonic()
        elif time.monotonic() - last_notice["at"] >= 30 * 60:  # reassure that the bot is alive
            last_notice["at"] = time.monotonic()
            opening = next_market_open(watch, datetime.now(timezone.utc))
            if opening is not None:
                console.print(f"[dim]{stamp}[/] Trh je zavřený, bot čeká. Nejbližší otevření: {local(opening):%d.%m. %H:%M}.")
            else:
                console.print(f"[dim]{stamp}[/] Bot běží, zatím žádný nový signál.")

    if once:
        show(trading_bot.run_once())
        return
    account = brk.get_account()
    if dry_run:
        mode = "SUCHÝ BĚH – nic se neposílá"
    elif brk.is_live:
        mode = "ŽIVÝ ÚČET – skutečné peníze"
    else:
        mode = "papírový účet – falešné peníze"
    console.print(Panel(
        f"Strategie: {strat.label()}\n"
        f"Symboly: {symbols_label(watch)} · interval {interval}\n"
        f"Broker: {brk.name} ({mode}) · kapitál {fmt(account.equity)} {account.currency}\n"
        f"Max. obchodů za den: {risk.config.max_trades_per_day} · max. pozic najednou: {risk.config.max_open_positions} "
        f"(každá do {risk.config.max_position_pct:.0f} % kapitálu) · short: {'ano' if risk.config.allow_short else 'ne'}\n"
        "Bot vyhodnotí každou uzavřenou svíčku; mimo obchodní hodiny čeká. Zastavíš ho klávesami Ctrl+C.",
        title="Obchodní bot", border_style="red" if brk.is_live and not dry_run else "blue",
    ))
    if interval_seconds(interval) <= 60 and risk.config.max_trades_per_day < 30:
        console.print(f"[yellow]Na minutových svíčkách bot obchoduje často a limit {risk.config.max_trades_per_day} "
                      "obchodů za den rychle vyčerpá. Zvyš ho volbou --max-trades nebo v .env (DT_MAX_TRADES_PER_DAY).[/]")
    stop_event = threading.Event()
    try:
        trading_bot.run_forever(stop_event, on_decisions=show)
    except KeyboardInterrupt:
        stop_event.set()
        console.print("Bot zastaven. Otevřené pozice zůstávají – zkontroluj je příkazem `daytrader account`.")


@app.command()
@guarded
def journal(
    broker: BrokerOpt = None,
    provider: ProviderOpt = None,
    days: Annotated[int, typer.Option(help="Kolik dní zpět")] = 30,
    events: Annotated[int, typer.Option(help="Počet posledních událostí bota")] = 10,
    export: Annotated[Path | None, typer.Option(help="Uložit uzavřené obchody do CSV")] = None,
) -> None:
    """Deník: uzavřené obchody, statistiky a poslední události bota."""
    brk, _ = make_broker(broker, provider)
    since = datetime.now(timezone.utc) - pd.Timedelta(days=days)
    trips = round_trips(brk.get_fills(since))
    stats = journal_stats(trips)
    rows = [(METRIC_LABELS.get(k, k), format_metric(k, v)) for k, v in stats.items()]
    console.print(kv_table(rows, title=f"Statistiky za {days} dní ({brk.name})"))
    if not trips.empty:
        table = Table("Symbol", "Směr", "Vstup", "Výstup", "Ks", "Cena vstupu", "Cena výstupu", "P/L")
        for row in trips.tail(15).itertuples():
            table.add_row(row.symbol, row.side, f"{local(row.entry_time):%m-%d %H:%M}", f"{local(row.exit_time):%m-%d %H:%M}",
                          fmt(row.qty, 4), fmt(row.entry_price), fmt(row.exit_price), colored(row.pnl, 2, ""))
        console.print(table)
    if export:
        trips.to_csv(export, index=False)
        console.print(f"Obchody uloženy do {export}")
    log = journal_for().events(events)
    if not log.empty:
        console.print("[bold]Poslední události[/]")
        for row in log.itertuples():
            console.print(f"  [dim]{row.ts[:19]}[/] {row.symbol or '':8} {row.message}")


@app.command()
def dashboard(
    port: Annotated[int, typer.Option(help="Port webového rozhraní")] = 8501,
    headless: Annotated[bool, typer.Option(help="Neotvírat prohlížeč")] = False,
) -> None:
    """Spustí webový dashboard (Streamlit) na http://localhost:8501."""
    app_path = Path(__file__).parent / "dashboard" / "app.py"
    cmd = [
        sys.executable, "-m", "streamlit", "run", str(app_path), "--server.port", str(port),
        "--browser.gatherUsageStats", "false",
        "--theme.light.primaryColor", "#2a78d6", "--theme.dark.primaryColor", "#3987e5",
    ]
    if headless:
        cmd += ["--server.headless", "true"]
    raise typer.Exit(subprocess.call(cmd))


if __name__ == "__main__":  # pragma: no cover
    app()
