import pytest
from typer.testing import CliRunner

from daytrader.brokers import create_broker
from daytrader.cli import app
from daytrader.config import ConfigError, Settings, get_settings, parse_symbols
from daytrader.data import create_provider
from daytrader.sessions import SESSIONS, is_crypto_symbol, session_for_symbol

runner = CliRunner()


def test_settings_read_env_aliases(monkeypatch):
    monkeypatch.setenv("ALPACA_API_KEY", "abc123456")
    monkeypatch.setenv("ALPACA_SECRET_KEY", "")
    monkeypatch.setenv("DT_WATCHLIST", "aapl, msft;cez.pr")
    monkeypatch.setenv("DT_LIVE_TRADING", "false")
    settings = Settings()
    assert settings.alpaca_api_key.get_secret_value() == "abc123456"
    assert settings.alpaca_secret_key is None  # empty -> None
    assert settings.watchlist_symbols == ["AAPL", "MSFT", "CEZ.PR"]
    assert "3456" in settings.masked_summary()["Alpaca klíč"]
    assert "abc123456" not in str(settings.masked_summary())


def test_parse_symbols_deduplicates():
    assert parse_symbols("aapl,AAPL, btc/usdt\nspy") == ["AAPL", "BTC/USDT", "SPY"]


def test_live_trading_guard():
    settings = Settings(alpaca_api_key="k", alpaca_secret_key="s", alpaca_paper=False, live_trading=False)
    with pytest.raises(ConfigError, match="DT_LIVE_TRADING"):
        create_broker("alpaca", settings)
    with pytest.raises(ConfigError):
        create_broker("ccxt", Settings(ccxt_api_key="k", ccxt_secret="s", ccxt_sandbox=False))


def test_missing_keys_give_helpful_errors():
    with pytest.raises(ConfigError, match="ALPACA_API_KEY"):
        create_provider("alpaca", Settings())
    with pytest.raises(ConfigError):
        create_provider("nonsense", Settings())


def test_sessions():
    assert session_for_symbol("CEZ.PR").key == "prague"
    assert session_for_symbol("SAP.DE").key == "xetra"
    assert session_for_symbol("BTC-USD").key == "crypto"
    assert session_for_symbol("AAPL").key == "us"
    assert is_crypto_symbol("ETH/USDT") and not is_crypto_symbol("BRK-B")
    from datetime import datetime, timezone

    us = SESSIONS["us"]
    friday_evening = datetime(2026, 9, 25, 21, 0, tzinfo=timezone.utc)
    assert us.next_open(friday_evening).isoformat() == "2026-09-28T09:30:00-04:00"
    assert SESSIONS["crypto"].next_open(friday_evening) is None
    from daytrader.bot import next_market_open

    assert next_market_open(["AAPL", "CEZ.PR"], friday_evening).hour in (9, 3)  # Prague opens first (03:00 NY)
    assert next_market_open(["AAPL", "BTC-USD"], friday_evening) is None
    assert us.is_open(datetime(2026, 9, 21, 14, 0, tzinfo=timezone.utc))
    assert not us.is_open(datetime(2026, 9, 21, 21, 0, tzinfo=timezone.utc))
    assert us.minutes_to_close(datetime(2026, 9, 21, 19, 50, tzinfo=timezone.utc)) == pytest.approx(10)


@pytest.fixture
def demo_env(monkeypatch):
    monkeypatch.setenv("DT_DATA_PROVIDER", "demo")
    get_settings.cache_clear()


def test_cli_strategies_and_info(demo_env):
    result = runner.invoke(app, ["strategies"])
    assert result.exit_code == 0 and "orb" in result.output
    assert runner.invoke(app, ["info"]).exit_code == 0


def test_cli_analyze_and_backtest(demo_env):
    result = runner.invoke(app, ["analyze", "AAPL"])
    assert result.exit_code == 0, result.output
    assert "Signály" in result.output
    result = runner.invoke(app, ["backtest", "NVDA", "-s", "orb", "-p", "1mo", "--trades", "3"])
    assert result.exit_code == 0, result.output
    assert "Profit factor" in result.output


def test_cli_paper_trading_flow(demo_env):
    result = runner.invoke(app, ["buy", "BTC/USDT", "-y"])  # crypto trades 24/7 -> fills immediately
    assert result.exit_code == 0, result.output
    assert "Příkaz odeslán" in result.output
    result = runner.invoke(app, ["positions"])
    assert "BTC/USDT" in result.output
    assert runner.invoke(app, ["close", "BTC/USDT", "-y"]).exit_code == 0
    result = runner.invoke(app, ["journal"])
    assert result.exit_code == 0 and "Počet obchodů" in result.output


def test_cli_reports_errors_nicely(demo_env):
    result = runner.invoke(app, ["backtest", "AAPL", "-s", "does_not_exist"])
    assert result.exit_code == 1
    assert "Chyba" in result.output


def test_output_survives_legacy_windows_code_page(monkeypatch):
    import io
    import sys

    from daytrader.cli import ensure_utf8_output

    raw = io.BytesIO()
    legacy = io.TextIOWrapper(raw, encoding="cp1252")
    monkeypatch.setattr(sys, "stdout", legacy)
    ensure_utf8_output()
    print("Křížení EMA – strategie")
    legacy.flush()
    assert raw.getvalue().decode("utf-8").startswith("Křížení EMA")


def test_cli_bot_uses_bot_settings(monkeypatch):
    monkeypatch.setenv("DT_DATA_PROVIDER", "demo")
    monkeypatch.setenv("DT_BOT_STRATEGY", "ema_cross")
    monkeypatch.setenv("DT_BOT_PARAMS", "fast=5,slow=30")
    monkeypatch.setenv("DT_BOT_SYMBOLS", "BTC/USDT")
    get_settings.cache_clear()
    result = runner.invoke(app, ["bot", "--once", "--dry-run"])
    assert result.exit_code == 0, result.output
    assert "BTC/USDT" in result.output and "AAPL" not in result.output
    settings = get_settings()
    assert settings.bot_param_dict == {"fast": "5", "slow": "30"}
    assert "ema_cross" in settings.masked_summary()["Bot"]


def test_cli_minute_bot(demo_env):
    from daytrader.cli import risk_manager

    result = runner.invoke(app, ["bot", "--once", "--dry-run", "-s", "scalp", "-i", "1m", "--max-trades", "100",
                                 "--symbols", "BTC-USD"])
    assert result.exit_code == 0, result.output
    assert "BTC-USD" in result.output
    assert risk_manager(100).config.max_trades_per_day == 100
    assert risk_manager().config.max_trades_per_day == get_settings().max_trades_per_day


def test_cli_bot_with_more_positions_and_shorts(demo_env):
    from daytrader.cli import risk_manager

    result = runner.invoke(app, ["bot", "--once", "--dry-run", "-s", "scalp", "-i", "1m", "--symbols", "@krypto",
                                 "--max-positions", "10", "--short"])
    assert result.exit_code == 0, result.output
    assert "SHIB-USD" in result.output  # the whole group was used
    risk = risk_manager(max_positions=10, settings=get_settings().model_copy(update={"allow_short": True}))
    assert risk.config.max_open_positions == 10 and risk.config.max_position_pct == 10
    assert risk.config.allow_short
