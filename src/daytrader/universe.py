"""Ready-made symbol groups usable anywhere a symbol list is expected (``@us,@etf,AAPL``).

The lists favour liquid instruments: the bot trades many of them at once and quick
trades need tight spreads. Yahoo symbols unless the group says otherwise.
"""

from __future__ import annotations

UNIVERSES: dict[str, tuple[str, tuple[str, ...]]] = {
    "us": (
        "40 nejobchodovanějších amerických akcií",
        (
            "AAPL", "MSFT", "NVDA", "AMZN", "GOOGL", "META", "TSLA", "AMD", "AVGO", "NFLX",
            "PLTR", "INTC", "MU", "QCOM", "ORCL", "CRM", "ADBE", "UBER", "SHOP", "COIN",
            "MSTR", "HOOD", "SOFI", "PYPL", "BA", "JPM", "BAC", "WFC", "C", "GS",
            "XOM", "CVX", "PFE", "LLY", "UNH", "WMT", "COST", "DIS", "NKE", "F",
        ),
    ),
    "etf": (
        "14 likvidních amerických ETF (indexy, sektory, zlato, dluhopisy, 3× páka)",
        (
            "SPY", "QQQ", "IWM", "DIA", "XLF", "XLE", "XLK", "SMH", "TLT", "GLD",
            "SLV", "TQQQ", "SQQQ", "SOXL",
        ),
    ),
    "krypto": (
        "15 největších kryptoměn v USD (Yahoo, obchodují se nonstop)",
        (
            "BTC-USD", "ETH-USD", "SOL-USD", "XRP-USD", "BNB-USD", "DOGE-USD", "ADA-USD", "AVAX-USD",
            "LINK-USD", "DOT-USD", "LTC-USD", "BCH-USD", "TRX-USD", "XLM-USD", "SHIB-USD",
        ),
    ),
    "binance": (
        "30 kryptoměn na Binance v USDT (zdroj dat ccxt, nonstop)",
        (
            "BTC/USDT", "ETH/USDT", "SOL/USDT", "XRP/USDT", "BNB/USDT", "DOGE/USDT", "ADA/USDT",
            "AVAX/USDT", "LINK/USDT", "DOT/USDT", "LTC/USDT", "BCH/USDT", "TRX/USDT", "XLM/USDT",
            "SHIB/USDT", "NEAR/USDT", "ATOM/USDT", "UNI/USDT", "ETC/USDT", "FIL/USDT", "APT/USDT",
            "ARB/USDT", "OP/USDT", "SUI/USDT", "PEPE/USDT", "AAVE/USDT", "INJ/USDT", "HBAR/USDT",
            "TON/USDT", "ICP/USDT",
        ),
    ),
    "praha": (
        "Akcie z pražské burzy (data o 20 minut zpožděná)",
        ("CEZ.PR", "KOMB.PR", "MONET.PR", "ERBAG.PR", "VIG.PR", "TABAK.PR", "KOFOL.PR", "CZG.PR"),
    ),
    "dax": (
        "15 německých akcií z indexu DAX (Xetra, data zpožděná)",
        (
            "SAP.DE", "SIE.DE", "ALV.DE", "DTE.DE", "AIR.DE", "MBG.DE", "BMW.DE", "BAS.DE",
            "BAYN.DE", "IFX.DE", "MUV2.DE", "DBK.DE", "VOW3.DE", "ADS.DE", "RHM.DE",
        ),
    ),
    "londyn": (
        "10 britských akcií (London Stock Exchange, data zpožděná)",
        ("SHEL.L", "AZN.L", "HSBA.L", "ULVR.L", "BP.L", "GSK.L", "RIO.L", "BARC.L", "LLOY.L", "VOD.L"),
    ),
}
ALIASES = {"crypto": "krypto", "prague": "praha", "london": "londyn"}


def universe(name: str) -> tuple[str, ...] | None:
    """Symbols of the group ``name`` (with or without the leading ``@``), ``None`` if unknown."""
    key = name.strip().lstrip("@").lower()
    entry = UNIVERSES.get(ALIASES.get(key, key))
    return entry[1] if entry else None


def universe_help() -> str:
    return ", ".join(f"@{key} ({len(symbols)})" for key, (_, symbols) in UNIVERSES.items())
