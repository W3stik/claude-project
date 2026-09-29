from typing import Any

from .base import Param, Strategy, positions_from_events
from .builtin import BollingerReversion, EmaCross, MacdMomentum, OpeningRangeBreakout, RsiReversion, VwapTrend

STRATEGIES: dict[str, type[Strategy]] = {
    cls.key: cls
    for cls in (EmaCross, VwapTrend, OpeningRangeBreakout, RsiReversion, BollingerReversion, MacdMomentum)
}


def get_strategy(key: str, **params: Any) -> Strategy:
    try:
        cls = STRATEGIES[key]
    except KeyError:
        raise ValueError(f"Neznámá strategie '{key}'. Dostupné: {', '.join(STRATEGIES)}") from None
    return cls(**params)


__all__ = ["STRATEGIES", "Param", "Strategy", "get_strategy", "positions_from_events"]
