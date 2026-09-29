"""Strategy interface.

A strategy turns bars into a *target position* series: ``1`` = be long, ``-1`` = be
short, ``0`` = be flat, evaluated at each bar's close. The backtester and the live bot
share the same execution rule: enter on the next bar when the target *changes*, exit
when the target moves away from the open position (or a stop / target / end-of-day
exit fires first).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, ClassVar

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class Param:
    name: str
    default: float | int | bool
    description: str
    min: float | None = None
    max: float | None = None
    step: float | None = None

    @property
    def kind(self) -> type:
        return type(self.default)

    def coerce(self, value: Any) -> float | int | bool:
        if self.kind is bool:
            if isinstance(value, str):
                return value.strip().lower() in ("1", "true", "yes", "ano", "on")
            return bool(value)
        number = self.kind(float(value)) if self.kind is int else float(value)
        if self.min is not None and number < self.min:
            raise ValueError(f"Parametr {self.name} musí být ≥ {self.min}.")
        if self.max is not None and number > self.max:
            raise ValueError(f"Parametr {self.name} musí být ≤ {self.max}.")
        return number


class Strategy(ABC):
    key: ClassVar[str]
    name: ClassVar[str]
    description: ClassVar[str]
    params_spec: ClassVar[tuple[Param, ...]] = ()
    intraday_only: ClassVar[bool] = False

    def __init__(self, **params: Any) -> None:
        spec = {p.name: p for p in self.params_spec}
        unknown = set(params) - set(spec)
        if unknown:
            raise ValueError(f"Neznámé parametry strategie {self.key}: {', '.join(sorted(unknown))}")
        self.params: dict[str, Any] = {p.name: p.default for p in self.params_spec}
        for name, value in params.items():
            self.params[name] = spec[name].coerce(value)
        self.validate()

    def validate(self) -> None:
        """Hook for cross-parameter validation."""

    @abstractmethod
    def generate_signals(self, bars: pd.DataFrame) -> pd.Series:
        """Target position (-1/0/1) for every bar, using data up to and including that bar."""

    def warmup_bars(self) -> int:
        numeric = [int(v) for v in self.params.values() if isinstance(v, (int, float)) and not isinstance(v, bool)]
        return max(numeric, default=20) * 3

    def label(self) -> str:
        args = ", ".join(f"{k}={v:g}" if isinstance(v, float) else f"{k}={v}" for k, v in self.params.items())
        return f"{self.name} ({args})" if args else self.name

    def __repr__(self) -> str:  # pragma: no cover - debugging helper
        return f"<{type(self).__name__} {self.params}>"


def positions_from_events(
    long_entry: pd.Series,
    long_exit: pd.Series,
    short_entry: pd.Series | None = None,
    short_exit: pd.Series | None = None,
) -> pd.Series:
    """Build a stateful target-position series from entry/exit event flags."""
    index = long_entry.index
    le = long_entry.fillna(False).to_numpy(dtype=bool)
    lx = long_exit.fillna(False).to_numpy(dtype=bool)
    se = short_entry.fillna(False).to_numpy(dtype=bool) if short_entry is not None else np.zeros(len(le), bool)
    sx = short_exit.fillna(False).to_numpy(dtype=bool) if short_exit is not None else np.zeros(len(le), bool)
    out = np.zeros(len(le), dtype=int)
    state = 0
    for i in range(len(le)):
        if state == 1 and lx[i]:
            state = 0
        elif state == -1 and sx[i]:
            state = 0
        if state == 0:
            if le[i]:
                state = 1
            elif se[i]:
                state = -1
        out[i] = state
    return pd.Series(out, index=index, name="signal")
