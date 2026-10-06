import pytest

from daytrader.config import ConfigError, parse_symbols
from daytrader.risk import RiskConfig
from daytrader.sessions import is_crypto_symbol, session_for_symbol
from daytrader.universe import UNIVERSES, universe, universe_help


def test_groups_expand_inside_symbol_lists():
    symbols = parse_symbols("aapl, @US, @crypto, BTC-USD")
    assert symbols[0] == "AAPL" and symbols.count("AAPL") == 1 and symbols.count("BTC-USD") == 1
    assert len(symbols) == len(set(symbols)) == 40 + 15
    assert universe("@krypto") == universe("crypto")
    with pytest.raises(ConfigError, match="@us"):
        parse_symbols("@nonsense")
    assert "@binance (30)" in universe_help()


@pytest.mark.parametrize("key", list(UNIVERSES))
def test_groups_are_clean_and_land_on_the_right_exchange(key):
    symbols = UNIVERSES[key][1]
    assert len(symbols) == len(set(symbols)) and all(s == s.upper().strip() for s in symbols)
    sessions = {session_for_symbol(s).key for s in symbols}
    expected = {"us": "us", "etf": "us", "krypto": "crypto", "binance": "crypto",
                "praha": "prague", "dax": "xetra", "londyn": "london"}[key]
    assert sessions == {expected}
    if key == "binance":
        assert all("/" in s and s.endswith("/USDT") for s in symbols)
    assert all(is_crypto_symbol(s) for s in symbols) == (expected == "crypto")


def test_more_positions_share_the_capital():
    config = RiskConfig(max_position_pct=25, max_open_positions=3)
    assert config.with_max_positions(3).max_position_pct == 25
    five = config.with_max_positions(5)
    assert five.max_open_positions == 5 and five.max_position_pct == 20
    assert config.with_max_positions(10).max_position_pct == 10
    assert config.max_open_positions == 3  # the original is left alone
