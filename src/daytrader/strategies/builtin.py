"""Classic, well-documented intraday strategies. They are starting points for learning and
research - none of them is expected to be profitable out of the box after costs."""

from __future__ import annotations

import numpy as np
import pandas as pd

from ..analysis.indicators import bollinger, ema, macd, rsi, session_keys, sma, vwap
from .base import Param, Strategy, positions_from_events


class EmaCross(Strategy):
    key = "ema_cross"
    name = "Křížení EMA"
    description = (
        "Long, když rychlá EMA je nad pomalou; short, když je pod ní. "
        "Jednoduché sledování trendu – funguje v trendech, v pohybu do strany generuje ztrátové obchody."
    )
    params_spec = (
        Param("fast", 9, "Perioda rychlé EMA", min=2, max=200, step=1),
        Param("slow", 21, "Perioda pomalé EMA", min=3, max=400, step=1),
    )

    def validate(self) -> None:
        if self.params["fast"] >= self.params["slow"]:
            raise ValueError("Rychlá EMA musí mít kratší periodu než pomalá.")

    def generate_signals(self, bars: pd.DataFrame) -> pd.Series:
        fast = ema(bars["close"], self.params["fast"])
        slow = ema(bars["close"], self.params["slow"])
        signal = np.sign(fast - slow).fillna(0).astype(int)
        return signal.rename("signal")


class RsiReversion(Strategy):
    key = "rsi_reversion"
    name = "RSI návrat k průměru"
    description = (
        "Nákup při přeprodaném RSI (pod dolní hranicí), výstup při návratu RSI ke středu. "
        "Short symetricky při překoupeném RSI. Volitelný trendový filtr SMA."
    )
    params_spec = (
        Param("period", 14, "Perioda RSI", min=2, max=100, step=1),
        Param("lower", 30.0, "Hranice přeprodanosti (vstup long)", min=1, max=50, step=1),
        Param("upper", 70.0, "Hranice překoupenosti (vstup short)", min=50, max=99, step=1),
        Param("exit", 50.0, "Úroveň RSI pro výstup", min=10, max=90, step=1),
        Param("trend_filter", 0, "SMA trendový filtr (0 = vypnuto)", min=0, max=400, step=10),
    )

    def validate(self) -> None:
        if not self.params["lower"] < self.params["exit"] < self.params["upper"]:
            raise ValueError("Musí platit: dolní hranice < výstup < horní hranice.")

    def generate_signals(self, bars: pd.DataFrame) -> pd.Series:
        close = bars["close"]
        r = rsi(close, self.params["period"])
        long_ok = short_ok = pd.Series(True, index=bars.index)
        if self.params["trend_filter"]:
            trend = sma(close, self.params["trend_filter"])
            long_ok, short_ok = close > trend, close < trend
        return positions_from_events(
            long_entry=(r < self.params["lower"]) & long_ok,
            long_exit=r > self.params["exit"],
            short_entry=(r > self.params["upper"]) & short_ok,
            short_exit=r < self.params["exit"],
        )


class BollingerReversion(Strategy):
    key = "bollinger"
    name = "Bollinger návrat k průměru"
    description = (
        "Nákup při zavření pod dolním Bollingerovým pásmem, výstup na středové linii. "
        "Short při zavření nad horním pásmem. Hodí se pro trh bez trendu."
    )
    params_spec = (
        Param("period", 20, "Perioda klouzavého průměru", min=5, max=200, step=1),
        Param("std", 2.0, "Šířka pásma v násobcích směrodatné odchylky", min=0.5, max=4, step=0.1),
    )

    def generate_signals(self, bars: pd.DataFrame) -> pd.Series:
        close = bars["close"]
        bands = bollinger(close, self.params["period"], self.params["std"])
        return positions_from_events(
            long_entry=close < bands["bb_lower"],
            long_exit=close >= bands["bb_mid"],
            short_entry=close > bands["bb_upper"],
            short_exit=close <= bands["bb_mid"],
        )


class VwapTrend(Strategy):
    key = "vwap_trend"
    name = "VWAP trend"
    description = (
        "Long, když je cena nad VWAP a rychlá EMA nad pomalou; výstup při zavření pod VWAP. "
        "Short zrcadlově. Typická intradenní strategie – VWAP se každý den počítá znovu."
    )
    intraday_only = True
    params_spec = (
        Param("fast", 9, "Perioda rychlé EMA", min=2, max=100, step=1),
        Param("slow", 21, "Perioda pomalé EMA", min=3, max=200, step=1),
    )

    def validate(self) -> None:
        if self.params["fast"] >= self.params["slow"]:
            raise ValueError("Rychlá EMA musí mít kratší periodu než pomalá.")

    def generate_signals(self, bars: pd.DataFrame) -> pd.Series:
        close = bars["close"]
        v = vwap(bars)
        fast = ema(close, self.params["fast"])
        slow = ema(close, self.params["slow"])
        return positions_from_events(
            long_entry=(close > v) & (fast > slow),
            long_exit=close < v,
            short_entry=(close < v) & (fast < slow),
            short_exit=close > v,
        )


class OpeningRangeBreakout(Strategy):
    key = "orb"
    name = "Průraz ranního rozpětí (ORB)"
    description = (
        "Po prvních N minutách obchodování vstup long při zavření nad maximem tohoto rozpětí, "
        "short při zavření pod minimem. Výstup při návratu do středu rozpětí, nejpozději na konci dne."
    )
    intraday_only = True
    params_spec = (
        Param("minutes", 15, "Délka ranního rozpětí v minutách", min=1, max=240, step=5),
        Param("max_entries", 1, "Max. vstupů za den", min=1, max=5, step=1),
        Param("exit_at_mid", True, "Výstup při návratu do středu rozpětí (jinak až na opačné straně)"),
    )

    def warmup_bars(self) -> int:
        return 1

    def generate_signals(self, bars: pd.DataFrame) -> pd.Series:
        keys = session_keys(bars.index)
        times = bars.index
        high = bars["high"].to_numpy()
        low = bars["low"].to_numpy()
        close = bars["close"].to_numpy()
        window = pd.Timedelta(minutes=int(self.params["minutes"]))
        max_entries = int(self.params["max_entries"])
        out = np.zeros(len(bars), dtype=int)
        day = None
        or_end = None
        or_high, or_low = -np.inf, np.inf
        entries = 0
        state = 0
        for i in range(len(bars)):
            if keys[i] != day:
                day, or_end = keys[i], times[i] + window
                or_high, or_low, entries, state = -np.inf, np.inf, 0, 0
            if times[i] < or_end:
                or_high, or_low = max(or_high, high[i]), min(or_low, low[i])
                state = 0
            else:
                mid = (or_high + or_low) / 2
                if state == 1 and close[i] < (mid if self.params["exit_at_mid"] else or_low):
                    state = 0
                elif state == -1 and close[i] > (mid if self.params["exit_at_mid"] else or_high):
                    state = 0
                elif state == 0 and entries < max_entries:
                    if close[i] > or_high:
                        state, entries = 1, entries + 1
                    elif close[i] < or_low:
                        state, entries = -1, entries + 1
            out[i] = state
        return pd.Series(out, index=bars.index, name="signal")


class Scalp(Strategy):
    key = "scalp"
    name = "Skalpování (minutové svíčky)"
    description = (
        "Krátké obchody na minutových svíčkách. V rostoucím trendu (cena nad VWAP, rychlá EMA nad pomalou) koupí, "
        "když se po krátkém poklesu RSI otočí z přeprodané zóny nahoru. Prodá, jakmile RSI vyskočí nahoru (malý "
        "zisk), když cena zavře pod VWAP, nebo nejpozději po zadaném počtu svíček. Short zrcadlově."
    )
    intraday_only = True
    params_spec = (
        Param("fast", 20, "Rychlá EMA trendového filtru", min=2, max=200, step=1),
        Param("slow", 50, "Pomalá EMA trendového filtru", min=3, max=400, step=5),
        Param("rsi", 5, "Perioda RSI", min=2, max=50, step=1),
        Param("dip", 35.0, "Vstup, když se RSI vrátí nad tuto hranici", min=5, max=49, step=1),
        Param("take", 65.0, "Výstup se ziskem, když RSI dosáhne této hranice", min=51, max=95, step=1),
        Param("max_hold", 10, "Nejdelší držení pozice (svíček)", min=1, max=240, step=1),
    )

    def validate(self) -> None:
        if self.params["fast"] >= self.params["slow"]:
            raise ValueError("Rychlá EMA musí mít kratší periodu než pomalá.")

    def generate_signals(self, bars: pd.DataFrame) -> pd.Series:
        close = bars["close"]
        c = close.to_numpy()
        fast = ema(close, self.params["fast"]).to_numpy()
        slow = ema(close, self.params["slow"]).to_numpy()
        v = vwap(bars).to_numpy()
        r = rsi(close, self.params["rsi"]).to_numpy()
        keys = session_keys(bars.index)
        dip, take, max_hold = self.params["dip"], self.params["take"], int(self.params["max_hold"])
        out = np.zeros(len(bars), dtype=int)
        state = held = 0
        for i in range(1, len(bars)):
            if keys[i] != keys[i - 1]:
                state = 0  # positions are closed at the end of every session
            if state:
                held += 1
                if state == 1 and (r[i] >= take or c[i] < v[i] or held >= max_hold):
                    state = 0
                elif state == -1 and (r[i] <= 100 - take or c[i] > v[i] or held >= max_hold):
                    state = 0
                out[i] = state
                continue  # a new trade needs a new dip, not the bar of the exit
            if c[i] > v[i] and fast[i] > slow[i] and r[i - 1] < dip <= r[i]:
                state, held = 1, 0
            elif c[i] < v[i] and fast[i] < slow[i] and r[i - 1] > 100 - dip >= r[i]:
                state, held = -1, 0
            out[i] = state
        return pd.Series(out, index=bars.index, name="signal")


class MacdMomentum(Strategy):
    key = "macd"
    name = "MACD momentum"
    description = (
        "Long, když je MACD nad signální linií, short, když je pod ní. "
        "Volitelný filtr nulové linie obchoduje jen ve směru hlavního momenta."
    )
    params_spec = (
        Param("fast", 12, "Rychlá EMA", min=2, max=100, step=1),
        Param("slow", 26, "Pomalá EMA", min=3, max=200, step=1),
        Param("signal", 9, "Signální linie", min=2, max=50, step=1),
        Param("zero_filter", False, "Long jen nad nulou, short jen pod nulou"),
    )

    def validate(self) -> None:
        if self.params["fast"] >= self.params["slow"]:
            raise ValueError("Rychlá EMA musí mít kratší periodu než pomalá.")

    def generate_signals(self, bars: pd.DataFrame) -> pd.Series:
        m = macd(bars["close"], self.params["fast"], self.params["slow"], self.params["signal"])
        signal = np.sign(m["macd"] - m["macd_signal"]).fillna(0).astype(int)
        if self.params["zero_filter"]:
            signal = signal.where(~((signal > 0) & (m["macd"] <= 0)), 0)
            signal = signal.where(~((signal < 0) & (m["macd"] >= 0)), 0)
        return signal.rename("signal")
