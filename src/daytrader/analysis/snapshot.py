"""A compact, explainable technical read-out of one symbol (used by CLI, scanner, UI and AI)."""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass, field
from typing import Any

import pandas as pd

from ..timeframes import is_intraday
from .indicators import add_indicators, session_relative_volume
from .levels import session_levels, swing_levels


@dataclass
class TechnicalSnapshot:
    symbol: str
    interval: str
    timestamp: str
    price: float
    change_pct: float | None
    ema_fast: float | None
    ema_slow: float | None
    vwap: float | None
    rsi: float | None
    macd_hist: float | None
    atr: float | None
    atr_pct: float | None
    adx: float | None
    bb_pct_b: float | None
    rvol: float | None
    trend: str
    score: int
    bias: str
    signals: list[str] = field(default_factory=list)
    levels: dict[str, float] = field(default_factory=dict)
    swing: dict[str, list[float]] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        for key, value in list(data.items()):
            if isinstance(value, float):
                data[key] = round(value, 4)
        data["levels"] = {k: round(v, 4) for k, v in self.levels.items()}
        return data


def _num(value: Any) -> float | None:
    try:
        value = float(value)
    except (TypeError, ValueError):
        return None
    return value if math.isfinite(value) else None


def _fmt(value: float | None, digits: int = 2) -> str:
    return "—" if value is None else f"{value:.{digits}f}"


def bias_label(score: int) -> str:
    if score >= 30:
        return "býčí"
    if score <= -30:
        return "medvědí"
    return "neutrální"


def build_snapshot(
    bars: pd.DataFrame,
    symbol: str = "",
    interval: str = "5m",
    ema_fast: int = 9,
    ema_slow: int = 21,
    stop_atr_mult: float = 1.5,
) -> TechnicalSnapshot:
    if bars.empty:
        raise ValueError("Žádná data pro analýzu.")
    df = add_indicators(bars, ema_fast=ema_fast, ema_slow=ema_slow)
    last = df.iloc[-1]
    price = float(last["close"])
    intraday = is_intraday(interval)

    e_fast = _num(last[f"ema{ema_fast}"])
    e_slow = _num(last[f"ema{ema_slow}"])
    vwap = _num(last["vwap"]) if intraday else None
    rsi = _num(last["rsi"])
    hist = _num(last["macd_hist"])
    prev_hist = _num(df["macd_hist"].iloc[-2]) if len(df) > 1 else None
    atr = _num(last["atr"])
    atr_pct = atr / price * 100 if atr and price else None
    adx = _num(last["adx"])
    pct_b = _num(last["bb_pct_b"])
    sma200 = _num(last["sma200"])
    rvol = session_relative_volume(bars) if intraday else _num(last["rvol"])
    levels = session_levels(bars) if intraday else {}

    if intraday:
        change_pct = (price / levels["prev_close"] - 1) * 100 if "prev_close" in levels else None
    else:
        change_pct = (price / float(df["close"].iloc[-2]) - 1) * 100 if len(df) > 1 else None

    score = 0.0
    signals: list[str] = []

    # Trend (EMA alignment)
    if e_fast is not None and e_slow is not None:
        if e_fast > e_slow and price > e_fast:
            score += 25
            signals.append(f"EMA {ema_fast} je nad EMA {ema_slow} a cena nad oběma – krátkodobý trend roste.")
        elif e_fast < e_slow and price < e_fast:
            score -= 25
            signals.append(f"EMA {ema_fast} je pod EMA {ema_slow} a cena pod oběma – krátkodobý trend klesá.")
        elif e_fast > e_slow:
            score += 10
            signals.append(f"EMA {ema_fast} nad EMA {ema_slow}, ale cena se vrací k průměrům – trend slábne.")
        else:
            score -= 10
            signals.append(f"EMA {ema_fast} pod EMA {ema_slow}, cena se ale odráží nahoru – možný obrat.")

    # VWAP
    if vwap is not None:
        if price > vwap:
            score += 15
            signals.append(f"Cena je nad VWAP ({_fmt(vwap)}) – intradenní kupci mají navrch.")
        else:
            score -= 15
            signals.append(f"Cena je pod VWAP ({_fmt(vwap)}) – intradenní prodejci mají navrch.")

    # MACD momentum
    if hist is not None:
        rising = prev_hist is not None and hist > prev_hist
        if hist > 0:
            score += 15
            signals.append("MACD je nad signální linií" + (" a histogram roste." if rising else ", ale histogram slábne."))
        else:
            score -= 15
            signals.append("MACD je pod signální linií" + (", histogram se ale zlepšuje." if rising else " a histogram klesá."))

    # RSI
    if rsi is not None:
        if rsi >= 70:
            score -= 5
            signals.append(f"RSI {rsi:.0f} – překoupeno, roste riziko návratu k průměru.")
        elif rsi <= 30:
            score += 5
            signals.append(f"RSI {rsi:.0f} – přeprodáno, možný odraz (ale v silném poklesu může zůstat nízko).")
        elif rsi >= 55:
            score += 10
            signals.append(f"RSI {rsi:.0f} – býčí momentum.")
        elif rsi <= 45:
            score -= 10
            signals.append(f"RSI {rsi:.0f} – medvědí momentum.")
        else:
            signals.append(f"RSI {rsi:.0f} – neutrální.")

    # Long-term trend
    if sma200 is not None:
        if price > sma200:
            score += 10
        else:
            score -= 10
        signals.append(
            f"Cena je {'nad' if price > sma200 else 'pod'} SMA 200 ({_fmt(sma200)}) – "
            f"delší trend na tomto intervalu je {'rostoucí' if price > sma200 else 'klesající'}."
        )

    # Trend strength
    if adx is not None:
        if adx >= 25:
            signals.append(f"ADX {adx:.0f} – silný trend, strategie sledující trend mají výhodu.")
        elif adx < 20:
            score *= 0.7
            signals.append(f"ADX {adx:.0f} – slabý trend / pohyb do strany, pozor na falešné průrazy.")

    # Bollinger position
    if pct_b is not None:
        if pct_b > 1:
            signals.append("Cena je nad horním Bollingerovým pásmem – silný pohyb, ale natažený.")
        elif pct_b < 0:
            signals.append("Cena je pod dolním Bollingerovým pásmem – silný výprodej, ale natažený.")

    # Volume
    if rvol is not None:
        if rvol >= 2:
            signals.append(f"Relativní objem {rvol:.1f}× – titul je 'v pohybu' (in play).")
        elif rvol < 0.6:
            signals.append(f"Relativní objem {rvol:.1f}× – nízký zájem, horší likvidita a slabší signály.")

    # Gap
    gap = levels.get("gap_pct")
    if gap is not None and abs(gap) >= 1:
        signals.append(f"Dnešní gap {gap:+.1f} % oproti včerejší závěrečné.")

    # Volatility / stop suggestion
    if atr is not None and atr_pct is not None:
        signals.append(
            f"ATR {_fmt(atr)} ({atr_pct:.2f} % ceny) – stop-loss {stop_atr_mult:g}× ATR = "
            f"{_fmt(stop_atr_mult * atr)} od vstupu."
        )

    score_int = int(max(-100, min(100, round(score))))
    if e_fast is not None and e_slow is not None and adx is not None and adx >= 20:
        trend = "rostoucí" if e_fast > e_slow else "klesající"
    elif e_fast is not None and e_slow is not None and abs(e_fast - e_slow) / price > 0.002:
        trend = "rostoucí" if e_fast > e_slow else "klesající"
    else:
        trend = "do strany"

    return TechnicalSnapshot(
        symbol=symbol,
        interval=interval,
        timestamp=df.index[-1].isoformat(),
        price=price,
        change_pct=change_pct,
        ema_fast=e_fast,
        ema_slow=e_slow,
        vwap=vwap,
        rsi=rsi,
        macd_hist=hist,
        atr=atr,
        atr_pct=atr_pct,
        adx=adx,
        bb_pct_b=pct_b,
        rvol=rvol,
        trend=trend,
        score=score_int,
        bias=bias_label(score_int),
        signals=signals,
        levels=levels,
        swing=swing_levels(bars.tail(300)),
    )
