"""Position sizing and pre-trade risk checks.

The rules implement the basics every day trader should follow: risk a small fixed
fraction of equity per trade, always know your stop, cap position size, stop trading
for the day after a maximum daily loss, and avoid over-trading.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from .config import Settings
from .models import Account, Position, Side


@dataclass
class RiskConfig:
    risk_per_trade_pct: float = 1.0
    max_position_pct: float = 25.0
    max_daily_loss_pct: float = 3.0
    max_open_positions: int = 3
    max_trades_per_day: int = 10
    stop_atr_mult: float = 1.5
    take_profit_r: float = 2.0
    require_stop_loss: bool = True
    allow_short: bool = False

    @classmethod
    def from_settings(cls, settings: Settings) -> "RiskConfig":
        return cls(
            risk_per_trade_pct=settings.risk_per_trade_pct,
            max_position_pct=settings.max_position_pct,
            max_daily_loss_pct=settings.max_daily_loss_pct,
            max_open_positions=settings.max_open_positions,
            max_trades_per_day=settings.max_trades_per_day,
            stop_atr_mult=settings.stop_atr_mult,
            take_profit_r=settings.take_profit_r,
            allow_short=settings.allow_short,
        )


@dataclass
class RiskCheck:
    allowed: bool = True
    reasons: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def deny(self, reason: str) -> None:
        self.allowed = False
        self.reasons.append(reason)


def position_size(
    equity: float,
    entry: float,
    stop: float | None,
    risk_pct: float,
    max_position_pct: float,
    fractional: bool = False,
) -> float:
    """Quantity such that hitting the stop loses ``risk_pct`` % of equity,
    capped so the position is at most ``max_position_pct`` % of equity."""
    if equity <= 0 or entry <= 0:
        return 0.0
    max_qty = equity * max_position_pct / 100 / entry
    if stop is not None and stop > 0 and abs(entry - stop) > 0:
        qty = equity * risk_pct / 100 / abs(entry - stop)
    else:
        qty = max_qty
    qty = min(qty, max_qty)
    if fractional:
        return math.floor(qty * 1e6) / 1e6
    return float(math.floor(qty))


def stop_and_target(
    side: Side, entry: float, atr: float | None, stop_atr_mult: float, take_profit_r: float | None
) -> tuple[float | None, float | None]:
    """ATR-based stop and an R-multiple take-profit for a new position."""
    if atr is None or not math.isfinite(atr) or atr <= 0 or stop_atr_mult <= 0:
        return None, None
    distance = atr * stop_atr_mult
    if side is Side.BUY:
        stop = entry - distance
        target = entry + distance * take_profit_r if take_profit_r else None
    else:
        stop = entry + distance
        target = entry - distance * take_profit_r if take_profit_r else None
    if stop <= 0:
        return None, target
    return stop, target


class RiskManager:
    def __init__(self, config: RiskConfig | None = None) -> None:
        self.config = config or RiskConfig()

    def size(self, equity: float, entry: float, stop: float | None, fractional: bool = False) -> float:
        return position_size(
            equity, entry, stop, self.config.risk_per_trade_pct, self.config.max_position_pct, fractional
        )

    def levels(self, side: Side, entry: float, atr: float | None) -> tuple[float | None, float | None]:
        return stop_and_target(side, entry, atr, self.config.stop_atr_mult, self.config.take_profit_r)

    def daily_loss_hit(self, account: Account) -> bool:
        pct = account.day_pnl_pct
        return pct is not None and pct <= -abs(self.config.max_daily_loss_pct)

    def check_new_trade(
        self,
        account: Account,
        positions: list[Position],
        symbol: str,
        side: Side,
        qty: float,
        entry: float,
        stop: float | None,
        trades_today: int = 0,
    ) -> RiskCheck:
        cfg = self.config
        check = RiskCheck()
        if qty <= 0:
            check.deny("Vypočtené množství je 0 – stop je příliš daleko nebo je účet příliš malý.")
        if side is Side.SELL and not cfg.allow_short:
            check.deny("Shortování je v nastavení zakázané (DT_ALLOW_SHORT=false).")
        if self.daily_loss_hit(account):
            check.deny(
                f"Dosažen denní limit ztráty {cfg.max_daily_loss_pct:g} % – dnes už žádné nové obchody."
            )
        others = [p for p in positions if p.symbol != symbol and p.qty != 0]
        if len(others) >= cfg.max_open_positions:
            check.deny(f"Otevřeno už {len(others)} pozic (limit {cfg.max_open_positions}).")
        if trades_today >= cfg.max_trades_per_day:
            check.deny(f"Dnes už proběhlo {trades_today} obchodů (limit {cfg.max_trades_per_day}).")
        if cfg.require_stop_loss and stop is None:
            check.deny("Obchod nemá stop-loss – bez něj se neobchoduje.")
        notional = qty * entry
        if account.equity > 0 and notional > account.equity * cfg.max_position_pct / 100 * 1.001:
            check.deny(
                f"Pozice {notional:,.0f} přesahuje {cfg.max_position_pct:g} % kapitálu."
            )
        if notional > account.buying_power * 1.001:
            check.deny(f"Nedostatečná kupní síla ({account.buying_power:,.0f}).")
        if stop is not None and account.equity > 0:
            risk_pct = abs(entry - stop) * qty / account.equity * 100
            if risk_pct > cfg.risk_per_trade_pct * 1.5:
                check.warnings.append(f"Riziko obchodu {risk_pct:.2f} % kapitálu je nad plánem.")
        if (
            account.pattern_day_trader is False
            and account.day_trade_count is not None
            and account.day_trade_count >= 3
            and account.equity < 25_000
        ):
            check.warnings.append(
                "Pozor na pravidlo PDT (US maržové účty pod 25 000 USD): už máš "
                f"{account.day_trade_count} day trady za posledních 5 obchodních dní."
            )
        return check
