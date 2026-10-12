# CLAUDE.md – předávací poznámky pro agenta

Repozitář `W3stik/claude-project` obsahuje **dvě nezávislé aplikace**. Uživatel komunikuje česky;
texty v aplikacích, komentáře v kódu, README a hlášky jsou česky. Commit zprávy jsou anglicky
(rozkazovací věta v předmětu, tělo vysvětluje proč).

| Aplikace | Kde | Jazyk / stack | Dokumentace |
|---|---|---|---|
| **Daytrader** – nástroj pro day trading (analýza, backtesty, papírové i živé obchodování, bot, dashboard) | kořen repozitáře (`src/daytrader`, `tests`, `*.bat`, `pyproject.toml`) | Python 3.10–3.14, Typer CLI, Streamlit + Plotly, pandas, SQLite | `README.md` (pro uživatele) + tento soubor |
| **Booster Lab** – PWA simulátor otevírání balíčků Pokémon TCG | `pokemon-packs/` | TypeScript, Vite, bez frameworku, Vitest | `pokemon-packs/README.md` (pro uživatele) + **`pokemon-packs/CLAUDE.md`** (pro agenta, podrobně) |

Aplikace spolu nesdílejí kód ani závislosti. Při práci na jedné se druhé nedotýkej.

## Větve (stav k 12. 10. 2026)

- `claude/day-trading-app-66jnnu` – **výchozí větev repozitáře**, obsahuje jen Daytrader.
- `claude/awesome-cori-5nrn80` – výchozí větev + celý Booster Lab (`pokemon-packs/`, workflow
  `.github/workflows/pokemon-packs.yml`, tyto soubory CLAUDE.md/AGENTS.md). **Zatím nesloučeno**
  a neexistuje k ní PR. Daytrader se v ní nezměnil.
- GitHub Pages se nasazují jen z výchozí větve (viz Booster Lab → nasazení). Dokud se větev
  nesloučí a v nastavení repozitáře se nezapne *Settings → Pages → Source: GitHub Actions*,
  aplikace veřejně neběží.

## CI (`.github/workflows/`)

- `tests.yml` – pytest Daytraderu na Ubuntu (Python 3.10/3.12/3.14) a macOS, plus kontrola
  `install.bat` na Windows. Spouští se na **každý** push a PR (i když se mění jen `pokemon-packs/`).
- `pokemon-packs.yml` – `npm ci`, `npm test`, `npm run prices` (smí selhat), `npm run build`,
  nahrání artefaktu pro Pages; nasazení jen z výchozí větve, denně v 5:17 UTC (čerstvé ceny) nebo ručně.
  Spouští se jen při změně `pokemon-packs/**` nebo toho workflow.

## Daytrader – jak s ním pracovat

```bash
python -m venv .venv && source .venv/bin/activate      # Windows: .venv\Scripts\Activate.ps1
pip install -e ".[dev]"                                 # dev = all (ccxt + anthropic) + pytest
pytest                                                  # běží offline, ~celá sada během chvilky
daytrader --help                                        # CLI (entry point daytrader.cli:app)
daytrader dashboard                                     # Streamlit na http://localhost:8501
```

- Uživatel je na **Windows**: instaluje `install.bat` (vytvoří `.venv`, `pip install -e ".[all]"`,
  zkopíruje `.env.example` → `.env`), spouští `start.bat` (dashboard), `bot.bat`, `bot-1min.bat`,
  `bot-max.bat`, `bot-krypto.bat`. Soubory `*.bat` **musí mít konce řádků CRLF** (`.gitattributes`:
  `*.bat -text`) a jen ASCII text (bez diakritiky v `echo`). CI je na Windows reálně spouští.
- Konzole Windows: výstup CLI musí přežít starou kódovou stránku (`cli.ensure_utf8_output`,
  launchery nastavují `PYTHONUTF8=1`).
- Nastavení: `src/daytrader/config.py` (pydantic-settings, prefix `DT_`, soubor `.env`);
  vzor všech proměnných je v `.env.example`. Data (papírový účet, deník) v `~/.daytrader` (`DT_DATA_DIR`).
- Struktura:
  - `analysis/` indikátory, úrovně, `snapshot` (technický přehled + skóre −100..100)
  - `strategies/` strategie vracející signály −1/0/1 (`builtin.py`: ema_cross, vwap_trend, orb,
    rsi_reversion, bollinger, macd, scalp); nová strategie dědí `strategies/base.py:Strategy`
    a přidá se do `STRATEGIES`
  - `backtest/` engine (signál na zavření svíčky, obchod na otevření další; když stop i TP
    v jedné svíčce → konzervativně stop) a metriky
  - `data/` zdroje dat: yahoo (výchozí), alpaca, ccxt, synthetic (`demo`, offline)
  - `brokers/` paper (lokální SQLite simulace), alpaca, ccxt; rozhraní `brokers/base.py:Broker`
  - `risk.py` velikost pozice z rizika a kontroly (denní ztráta, počet pozic/obchodů, short)
  - `trading.py` plán a provedení ručního příkazu, `bot.py` automatický bot,
    `journal.py` deník a statistiky, `scanner.py`, `sessions.py` obchodní hodiny burz,
    `universe.py` skupiny symbolů (`@us`, `@etf`, `@krypto`, `@binance`, `@praha`, `@dax`, `@londyn`)
  - `ai.py` volitelný AI komentář přes Claude API (`ANTHROPIC_API_KEY`, model v `DT_AI_MODEL`,
    výchozí `claude-opus-5-5`; tabulka cen v `ai.PRICING`)
  - `dashboard/` Streamlit stránky, `cli.py` příkazy (info, quote, analyze, scan, strategies,
    backtest, optimize, account, positions, orders, buy, sell, close, close-all, cancel,
    paper-reset, bot, journal, dashboard)

### Bezpečnostní pravidla Daytraderu (neměnit bez výslovného pokynu uživatele)

- Výchozí je **papírový účet**. Živé obchodování je zablokované, dokud `DT_LIVE_TRADING=true`;
  každý živý příkaz v CLI se potvrzuje napsáním `ANO`; živého bota nejde spustit z dashboardu.
- Alpaca `ALPACA_PAPER=true` a CCXT `CCXT_SANDBOX=true` jsou výchozí.
- Nikdy necommituj `.env` ani klíče (jsou v `.gitignore`).
- Testy nesmí sahat na síť: používají generovaná data a mocky API (Alpaca, CCXT, Yahoo, Claude).

## Booster Lab – stručně

```bash
cd pokemon-packs
npm install
npm run dev        # http://localhost:5173
npm test           # Vitest: generátor balíčků, šance, regál
npm run build      # tsc --noEmit + vite build → dist/
npm run data       # znovu stáhne 10 nejnovějších sad z GitHubu (PokemonTCG/pokemon-tcg-data)
npm run prices     # stáhne ceny z TCGdex do public/data/prices.json (necommituje se)
```

Vše ostatní (architektura, zdroje dat a co z nich je ověřené, 3D nástrahy, nápady na další práci)
je v **`pokemon-packs/CLAUDE.md`**. Přečti si ho před jakoukoli změnou v `pokemon-packs/`.

## Obecné zvyklosti

- Před commitem spusť testy dotčené aplikace (`pytest` / `npm test && npm run build`).
- Měň jen to, co úkol vyžaduje; nepřidávej závislosti bez důvodu.
- Odpovědi uživateli piš česky, stručně a konkrétně; když něco nešlo ověřit, řekni to.
