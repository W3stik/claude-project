import pytest

from daytrader.models import Account, Position, Side
from daytrader.risk import RiskConfig, RiskManager, position_size, stop_and_target


def account(equity=10_000.0, day_start=10_000.0, buying_power=None, **kw):
    return Account(equity=equity, cash=equity, buying_power=equity if buying_power is None else buying_power,
                   day_start_equity=day_start, **kw)


def test_position_size_by_risk_and_cap():
    assert position_size(10_000, 100, 98, risk_pct=1, max_position_pct=100) == 50
    assert position_size(10_000, 100, 99.9, risk_pct=1, max_position_pct=25) == 25  # capped at 25 %
    assert position_size(10_000, 100, None, risk_pct=1, max_position_pct=20) == 20
    assert position_size(1_000, 30_000, 29_000, 1, 100, fractional=True) == pytest.approx(0.01)
    assert position_size(0, 100, 99, 1, 100) == 0


def test_stop_and_target_for_both_sides():
    assert stop_and_target(Side.BUY, 100, 2, 1.5, 2) == (97, 106)
    assert stop_and_target(Side.SELL, 100, 2, 1.5, 2) == (103, 94)
    assert stop_and_target(Side.BUY, 100, float("nan"), 1.5, 2) == (None, None)


def test_check_allows_normal_trade():
    risk = RiskManager(RiskConfig(allow_short=True))
    check = risk.check_new_trade(account(), [], "AAPL", Side.BUY, 20, 100, 98)
    assert check.allowed, check.reasons


@pytest.mark.parametrize(
    "kwargs, fragment",
    [
        (dict(acct=account(equity=9_600, day_start=10_000)), "denní limit"),
        (dict(positions=[Position(s, 1, 10) for s in ("A", "B", "C")]), "pozic"),
        (dict(stop=None), "stop-loss"),
        (dict(side=Side.SELL, stop=102), "Shortování"),
        (dict(acct=account(buying_power=100)), "kupní síla"),
        (dict(trades_today=10), "obchodů"),
        (dict(qty=0), "množství"),
    ],
)
def test_check_denies(kwargs, fragment):
    risk = RiskManager(RiskConfig(allow_short=False))
    params = dict(acct=account(), positions=[], side=Side.BUY, qty=20, stop=98, trades_today=0)
    params.update(kwargs)
    check = risk.check_new_trade(params["acct"], params["positions"], "AAPL", params["side"], params["qty"], 100,
                                 params["stop"], params["trades_today"])
    assert not check.allowed
    assert any(fragment.lower() in reason.lower() for reason in check.reasons), check.reasons


def test_pdt_warning():
    risk = RiskManager()
    acct = account(pattern_day_trader=False, day_trade_count=3)
    check = risk.check_new_trade(acct, [], "AAPL", Side.BUY, 10, 100, 98)
    assert check.allowed
    assert any("PDT" in w for w in check.warnings)
