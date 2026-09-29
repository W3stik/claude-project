"""Plotly figures for the dashboard.

Colour roles (validated for colour-vision deficiencies against the chart surfaces):
up/profit = blue, down/loss = orange, one accent hue (aqua) for the fast EMA; every other
line is a neutral ink so identity never depends on hue alone (legend + end labels).
Each measure gets its own panel - no dual axes.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

from ..sessions import MarketSession
from ..timeframes import is_intraday

PALETTES: dict[str, dict[str, str]] = {
    "light": {
        "surface": "#fcfcfb",
        "ink": "#0b0b0b",
        "ink2": "#52514e",
        "muted": "#898781",
        "grid": "#e1e0d9",
        "axis": "#c3c2b7",
        "up": "#2a78d6",
        "down": "#eb6834",
        "accent": "#1baf7a",
        "band": "rgba(137, 135, 129, 0.10)",
    },
    "dark": {
        "surface": "#1a1a19",
        "ink": "#ffffff",
        "ink2": "#c3c2b7",
        "muted": "#898781",
        "grid": "#2c2c2a",
        "axis": "#383835",
        "up": "#3987e5",
        "down": "#d95926",
        "accent": "#199e70",
        "band": "rgba(137, 135, 129, 0.16)",
    },
}

FONT = 'system-ui, -apple-system, "Segoe UI", sans-serif'
OVERLAYS = ["EMA 9", "EMA 21", "VWAP", "Bollinger"]


def palette(mode: str) -> dict[str, str]:
    return PALETTES.get(mode, PALETTES["light"])


def _x(index: pd.DatetimeIndex) -> pd.DatetimeIndex:
    """Exchange-local wall-clock time without tz, so range breaks line up with session hours."""
    return index.tz_localize(None) if index.tz is not None else index


def _chart_times(values: pd.Series, tz) -> pd.DatetimeIndex:
    stamps = pd.DatetimeIndex(pd.to_datetime(values, utc=True))
    return _x(stamps.tz_convert(tz) if tz is not None else stamps)


def _rgba(hex_color: str, alpha: float) -> str:
    h = hex_color.lstrip("#")
    r, g, b = (int(h[i : i + 2], 16) for i in (0, 2, 4))
    return f"rgba({r}, {g}, {b}, {alpha})"


def _base_layout(fig: go.Figure, colors: dict[str, str], height: int) -> None:
    fig.update_layout(
        height=height,
        paper_bgcolor=colors["surface"],
        plot_bgcolor=colors["surface"],
        font={"family": FONT, "color": colors["ink2"], "size": 12},
        margin={"l": 8, "r": 128, "t": 36, "b": 32},
        hovermode="x unified",
        hoverlabel={"bgcolor": colors["surface"], "font": {"color": colors["ink"], "family": FONT}},
        legend={"orientation": "h", "yanchor": "bottom", "y": 1.0, "xanchor": "left", "x": 0, "font": {"color": colors["ink2"]}},
        bargap=0.15,
    )
    fig.update_xaxes(
        showgrid=False,
        linecolor=colors["axis"],
        tickfont={"color": colors["muted"]},
        showspikes=True,
        spikemode="across",
        spikethickness=1,
        spikecolor=colors["muted"],
        spikedash="solid",
        rangeslider_visible=False,
    )
    fig.update_yaxes(
        gridcolor=colors["grid"],
        gridwidth=1,
        zeroline=False,
        linecolor=colors["axis"],
        tickfont={"color": colors["muted"]},
        side="right",
    )


def _rangebreaks(interval: str, session: MarketSession | None) -> list[dict]:
    if session is None or session.is_24h:
        return []
    breaks: list[dict] = [{"bounds": ["sat", "mon"]}]
    if is_intraday(interval):
        close = session.close.hour + session.close.minute / 60
        open_ = session.open.hour + session.open.minute / 60
        breaks.append({"bounds": [close, open_], "pattern": "hour"})
    return breaks


def _end_labels(
    fig: go.Figure,
    labels: list[tuple[str, float]],
    colors: dict[str, str],
    row: int,
    span: float | None = None,
    panel_px: float = 400,
) -> None:
    """Direct labels in the right margin (past the price axis), nudged apart so they never overlap."""
    items = sorted((float(y), text) for text, y in labels if y is not None and np.isfinite(y))
    if not items:
        return
    gap = (span or 0) * 15 / max(panel_px, 1)  # ~15 px between label baselines
    placed: list[tuple[float, str]] = []
    for y, text in items:
        if placed and y - placed[-1][0] < gap:
            y = placed[-1][0] + gap
        placed.append((y, text))
    yref = "y" if row == 1 else f"y{row}"
    for y, text in placed:
        fig.add_annotation(
            x=1, xref="paper", y=y, yref=yref, text=text, xanchor="left", xshift=52, showarrow=False,
            font={"size": 11, "color": colors["ink2"]},
        )


def price_chart(
    df: pd.DataFrame,
    mode: str = "light",
    overlays: list[str] | None = None,
    interval: str = "5m",
    session: MarketSession | None = None,
    show_volume: bool = True,
    show_rsi: bool = True,
    show_macd: bool = True,
    trades: pd.DataFrame | None = None,
    height: int = 760,
    title: str | None = None,
) -> go.Figure:
    """Candlesticks + overlays; volume, RSI and MACD in separate panels.

    ``df`` must contain the columns produced by :func:`daytrader.analysis.add_indicators`.
    """
    colors = palette(mode)
    overlays = OVERLAYS[:3] if overlays is None else overlays
    panels = ["price"] + [p for p, on in (("volume", show_volume), ("rsi", show_rsi), ("macd", show_macd)) if on]
    weights = {"price": 0.58, "volume": 0.12, "rsi": 0.15, "macd": 0.15}
    heights = [weights[p] for p in panels]
    total = sum(heights)
    fig = make_subplots(
        rows=len(panels), cols=1, shared_xaxes=True, vertical_spacing=0.025,
        row_heights=[h / total for h in heights],
    )
    x = _x(df.index)
    row = {name: i + 1 for i, name in enumerate(panels)}
    price_labels: list[tuple[str, float]] = []

    fig.add_trace(
        go.Candlestick(
            x=x, open=df["open"], high=df["high"], low=df["low"], close=df["close"], name="Cena",
            increasing={"line": {"color": colors["up"], "width": 1}, "fillcolor": colors["up"]},
            decreasing={"line": {"color": colors["down"], "width": 1}, "fillcolor": colors["down"]},
        ),
        row=1, col=1,
    )

    if "Bollinger" in overlays and "bb_upper" in df:
        fig.add_trace(go.Scatter(x=x, y=df["bb_upper"], name="Bollinger", line={"color": colors["muted"], "width": 1},
                                 legendgroup="bb", hoverinfo="skip"), row=1, col=1)
        fig.add_trace(go.Scatter(x=x, y=df["bb_lower"], name="Bollinger dolní", line={"color": colors["muted"], "width": 1},
                                 fill="tonexty", fillcolor=colors["band"], legendgroup="bb", showlegend=False,
                                 hoverinfo="skip"), row=1, col=1)
        price_labels.append(("BB horní", df["bb_upper"].iloc[-1]))
        price_labels.append(("BB dolní", df["bb_lower"].iloc[-1]))
    line_specs = [
        ("EMA 9", "ema9", colors["accent"], "solid"),
        ("EMA 21", "ema21", colors["ink2"], "solid"),
        ("VWAP", "vwap", colors["ink"], "dot"),
    ]
    for label, column, color, dash in line_specs:
        if label in overlays and column in df and df[column].notna().any():
            fig.add_trace(go.Scatter(x=x, y=df[column], name=label, line={"color": color, "width": 2, "dash": dash},
                                     hovertemplate="%{y:.2f}"), row=1, col=1)
            price_labels.append((label, df[column].iloc[-1]))
    _end_labels(fig, price_labels, colors, 1, float(df["high"].max() - df["low"].min()) if len(df) else None,
                panel_px=height * heights[0] / total)

    if trades is not None and not trades.empty:
        entry_x = _chart_times(trades["entry_time"], df.index.tz)
        exit_x = _chart_times(trades["exit_time"], df.index.tz)
        longs = (trades["side"] == "long").to_numpy()
        for mask, symbol, color, name in (
            (longs, "triangle-up", colors["up"], "Vstup long"),
            (~longs, "triangle-down", colors["down"], "Vstup short"),
        ):
            if mask.any():
                fig.add_trace(go.Scatter(
                    x=entry_x[mask], y=trades["entry_price"].to_numpy()[mask], mode="markers", name=name,
                    marker={"symbol": symbol, "size": 11, "color": color, "line": {"color": colors["surface"], "width": 2}},
                    hovertemplate=name + " %{y:.2f}<extra></extra>",
                ), row=1, col=1)
        fig.add_trace(go.Scatter(
            x=exit_x, y=trades["exit_price"], mode="markers", name="Výstup",
            marker={"symbol": "circle", "size": 8, "color": colors["ink"], "line": {"color": colors["surface"], "width": 2}},
            customdata=trades["pnl"], hovertemplate="Výstup %{y:.2f} · P/L %{customdata:.2f}<extra></extra>",
        ), row=1, col=1)

    if "volume" in row:
        up = (df["close"] >= df["open"]).to_numpy()
        fig.add_trace(go.Bar(
            x=x, y=df["volume"], name="Objem", showlegend=False,
            marker={"color": np.where(up, colors["up"], colors["down"]), "opacity": 0.55, "line": {"width": 0}},
            hovertemplate="%{y:,.0f}",
        ), row=row["volume"], col=1)
        fig.update_yaxes(title_text="Objem", title_font={"size": 11}, row=row["volume"], col=1)

    if "rsi" in row and "rsi" in df:
        r = row["rsi"]
        for level in (30, 70):
            fig.add_hline(y=level, line={"color": colors["axis"], "width": 1}, row=r, col=1)
        fig.add_trace(go.Scatter(x=x, y=df["rsi"], name="RSI", showlegend=False, line={"color": colors["ink"], "width": 1.5},
                                 hovertemplate="%{y:.1f}"), row=r, col=1)
        fig.update_yaxes(range=[0, 100], tickvals=[30, 50, 70], title_text="RSI", title_font={"size": 11}, row=r, col=1)

    if "macd" in row and "macd" in df:
        r = row["macd"]
        hist = df["macd_hist"]
        fig.add_trace(go.Bar(
            x=x, y=hist, name="MACD histogram", showlegend=False,
            marker={"color": np.where(hist.fillna(0) >= 0, colors["up"], colors["down"]), "opacity": 0.55, "line": {"width": 0}},
            hovertemplate="%{y:.3f}",
        ), row=r, col=1)
        fig.add_trace(go.Scatter(x=x, y=df["macd"], name="MACD", showlegend=False, line={"color": colors["ink"], "width": 1.5},
                                 hovertemplate="%{y:.3f}"), row=r, col=1)
        fig.add_trace(go.Scatter(x=x, y=df["macd_signal"], name="Signál", showlegend=False,
                                 line={"color": colors["accent"], "width": 1.5}, hovertemplate="%{y:.3f}"), row=r, col=1)
        span = float(pd.concat([df["macd"], df["macd_signal"], hist]).agg(lambda v: v.max() - v.min()))
        _end_labels(fig, [("MACD", df["macd"].iloc[-1]), ("signál", df["macd_signal"].iloc[-1])], colors, r, span,
                    panel_px=height * heights[r - 1] / total)
        fig.update_yaxes(title_text="MACD", title_font={"size": 11}, row=r, col=1)

    _base_layout(fig, colors, height)
    breaks = _rangebreaks(interval, session)
    if breaks:
        fig.update_xaxes(rangebreaks=breaks)
    if title:
        fig.update_layout(title={"text": title, "font": {"color": colors["ink"], "size": 15}, "x": 0, "xanchor": "left"},
                          margin={"t": 64})
    return fig


def equity_chart(
    equity: pd.Series,
    benchmark: pd.Series | None = None,
    mode: str = "light",
    height: int = 460,
    interval: str = "1d",
    session: MarketSession | None = None,
) -> go.Figure:
    """Equity curve (strategy vs. buy & hold) with the drawdown in its own panel."""
    colors = palette(mode)
    fig = make_subplots(rows=2, cols=1, shared_xaxes=True, vertical_spacing=0.04, row_heights=[0.7, 0.3])
    x = _x(equity.index)
    labels = [("Strategie", equity.iloc[-1])]
    series = [equity]
    if benchmark is not None and not benchmark.empty:
        fig.add_trace(go.Scatter(x=x, y=benchmark, name="Buy & hold", line={"color": colors["muted"], "width": 1.5},
                                 hovertemplate="%{y:,.2f}"), row=1, col=1)
        labels.append(("Buy & hold", benchmark.iloc[-1]))
        series.append(benchmark)
    fig.add_trace(go.Scatter(x=x, y=equity, name="Strategie", line={"color": colors["up"], "width": 2},
                             hovertemplate="%{y:,.2f}"), row=1, col=1)
    combined = pd.concat(series)
    _end_labels(fig, labels, colors, 1, float(combined.max() - combined.min()), panel_px=height * 0.7)
    dd = (equity / equity.cummax() - 1) * 100
    fig.add_trace(go.Scatter(x=x, y=dd, name="Propad %", fill="tozeroy", showlegend=False,
                             line={"color": colors["down"], "width": 1}, fillcolor=_rgba(colors["down"], 0.25),
                             hovertemplate="%{y:.2f} %"), row=2, col=1)
    fig.update_yaxes(title_text="Kapitál", title_font={"size": 11}, row=1, col=1)
    fig.update_yaxes(title_text="Propad %", title_font={"size": 11}, row=2, col=1)
    _base_layout(fig, colors, height)
    breaks = _rangebreaks(interval, session)
    if breaks:
        fig.update_xaxes(rangebreaks=breaks)
    return fig


def pnl_bars(daily: pd.Series, mode: str = "light", height: int = 300) -> go.Figure:
    """Profit/loss per day: blue = profit, orange = loss."""
    colors = palette(mode)
    fig = go.Figure(go.Bar(
        x=[str(d) for d in daily.index], y=daily.values, name="P/L za den",
        marker={"color": np.where(daily.values >= 0, colors["up"], colors["down"]), "line": {"width": 0}, "cornerradius": 4},
        hovertemplate="%{x}: %{y:,.2f}<extra></extra>",
    ))
    fig.add_hline(y=0, line={"color": colors["axis"], "width": 1})
    _base_layout(fig, colors, height)
    fig.update_layout(hovermode="closest", showlegend=False, bargap=0.3)
    fig.update_xaxes(type="category", showspikes=False)
    return fig


def cumulative_chart(values: pd.Series, mode: str = "light", height: int = 300, name: str = "Kumulativní P/L") -> go.Figure:
    colors = palette(mode)
    fig = go.Figure(go.Scatter(
        x=[str(d) for d in values.index], y=values.values, name=name, mode="lines+markers",
        line={"color": colors["up"], "width": 2},
        marker={"size": 8, "color": colors["up"], "line": {"color": colors["surface"], "width": 2}},
        hovertemplate="%{x}: %{y:,.2f}<extra></extra>",
    ))
    fig.add_hline(y=0, line={"color": colors["axis"], "width": 1})
    _base_layout(fig, colors, height)
    fig.update_layout(showlegend=False)
    fig.update_xaxes(type="category")
    return fig
