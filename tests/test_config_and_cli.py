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
