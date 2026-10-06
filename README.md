# Daytrader – aplikace pro day trading

Nástroj pro intradenní obchodování v Pythonu: **technická analýza, scanner, backtesty,
papírové i živé obchodování přes API (Alpaca, kryptoburzy přes CCXT), obchodní bot,
deník obchodů a volitelný AI komentář**. Ovládá se z webového dashboardu nebo z příkazové řádky, obojí česky.

> ⚠️ **Upozornění.** Aplikace slouží ke vzdělávání a výzkumu, nejde o investiční doporučení.
> Day trading je vysoce rizikový a většina začínajících obchodníků prodělává.
> Výchozí nastavení proto obchoduje jen na **papírovém (simulovaném) účtu**. Živé obchodování
> je zablokované, dokud ho výslovně nepovolíš.

---

## Co aplikace umí

| Oblast | Funkce |
|---|---|
| **Analýza** | Svíčkový graf s EMA 9/21, VWAP a Bollingerovými pásmy, objem, RSI a MACD. Technické skóre −100 až +100 se slovním vysvětlením. Důležité úrovně: včerejší max/min/závěr, pivoty a swingové supporty a rezistence. Zprávy k titulu. |
| **Scanner** | Seřadí watchlist podle toho, co se právě hýbe: skóre trendu a momenta, relativní objem (RVOL), gap, RSI, ATR a vzdálenost od VWAP. |
| **Backtest** | 7 strategií (křížení EMA, VWAP trend, průraz ranního rozpětí ORB, RSI, Bollinger, MACD a minutové skalpování). Počítá s poplatky a skluzem, stop-lossem a take-profitem z ATR a zavíráním pozic na konci dne. Optimalizace parametrů s ověřením na odložených datech. |
| **Obchodování** | Papírový účet (lokální simulace), Alpaca (paper i live), kryptoburzy přes CCXT (Binance, Kraken, Coinbase, Bybit, Coinmate…). Před odesláním příkazu ukáže plán: velikost pozice dopočítanou z rizika, stop-loss, take-profit a poměr zisku k riziku. |
| **Řízení rizik** | Riziko ~1 % kapitálu na obchod, denní limit ztráty, maximum otevřených pozic, maximum obchodů za den, povinný stop-loss, upozornění na pravidlo PDT. |
| **Bot** | Automaticky obchoduje zvolenou strategii podle stejných pravidel jako backtest, klidně i každou minutu (skalpování). Umí „suchý běh“ bez odesílání příkazů. |
| **Deník** | Uzavřené obchody, úspěšnost, profit factor, P/L po dnech a export do CSV. |
| **AI komentář** | Volitelné shrnutí technické situace od Clauda (Claude API, placené podle spotřeby). |

## Co je zdarma a co se platí

| Služba | Cena | Poznámka |
|---|---|---|
| Aplikace, dashboard, demo data, papírový účet | **zdarma** | Vše běží lokálně na tvém počítači. |
| Yahoo Finance | **zdarma** | Bez registrace. Neoficiální zdroj, data mohou být zpožděná. |
| Alpaca – papírový účet a data IEX | **zdarma** | Stačí registrace e-mailem. |
| Alpaca – data SIP (celý objem trhu) | placené předplatné | Není potřeba, aplikace funguje s IEX. |
| Alpaca – živý účet | vkládáš vlastní peníze | Akcie a ETF bez komisí, regulatorní poplatky se ale mohou účtovat. Ověř si, jestli Alpaca přijímá klienty z ČR. |
| Kryptoburzy (CCXT) | testnet **zdarma** | Na ostrém účtu platíš poplatky burzy. |
| AI komentář (Claude API) | **placené podle spotřeby** | Přibližně 0,03–0,10 USD za jeden komentář s výchozím modelem. Aplikace po každém dotazu ukáže odhad ceny. Bez `ANTHROPIC_API_KEY` je vypnutý. |

---

## Instalace

Potřebuješ **Python 3.10–3.14** v 64bitové verzi ([python.org](https://www.python.org/downloads/)).
Na Windows při instalaci Pythonu zaškrtni **„Add python.exe to PATH“**.

### Windows – nejjednodušší cesta (bez příkazové řádky)

1. Na [stránce repozitáře](https://github.com/W3stik/claude-project) klikni na **Code → Download ZIP**
   a ZIP rozbal (nebo použij `git clone https://github.com/W3stik/claude-project.git`).
2. V rozbalené složce dvakrát klikni na **`install.bat`**. Vytvoří virtuální prostředí `.venv`
   a nainstaluje knihovny (několik minut).
3. Aplikaci pak spouštíš dvojklikem na **`start.bat`**. Dashboard se otevře v prohlížeči
   na http://localhost:8501. Černé okno nech otevřené, jinak se aplikace vypne.
4. Automatické obchodování na papírovém účtu spustíš dvojklikem na **`bot.bat`**
   (viz [Automatické obchodování](#automatické-obchodování-bot)). Bota, který obchoduje každou minutu,
   spustí **`bot-1min.bat`** (viz [Minutové obchodování](#minutové-obchodování-skalpování)).

### Windows – ručně v PowerShellu

Zadávej příkazy **po jednom**. Windows PowerShell nezná `&&` a místo `source` se prostředí aktivuje přes `Activate.ps1`.

```powershell
cd claude-project
py -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -e ".[all]"
copy .env.example .env
daytrader dashboard
```

### macOS / Linux

```bash
git clone https://github.com/W3stik/claude-project.git
cd claude-project
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[all]"
cp .env.example .env
daytrader dashboard
```

`.[all]` nainstaluje i podporu kryptoburz (CCXT) a AI komentáře. Bez nich stačí `pip install -e .`.

### Když instalace selže

| Hláška | Řešení |
|---|---|
| `The token '&&' is not a valid statement separator` | Windows PowerShell nezná `&&`. Zadávej příkazy po jednom, nebo použij `install.bat`. |
| `'python' is not recognized…` nebo se otevře Microsoft Store | Místo `python` použij `py`, nebo přeinstaluj Python se zaškrtnutým „Add python.exe to PATH“. |
| `…Activate.ps1 cannot be loaded because running scripts is disabled…` | Jednou spusť `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned`, nebo použij `install.bat` a `start.bat`. |
| `neither 'setup.py' nor 'pyproject.toml' found` | Nejsi ve složce aplikace. Nejdřív `cd` do složky, kde je `pyproject.toml`. |
| `Microsoft Visual C++ 14.0 or greater is required` / `Failed building wheel` | Pro tvůj Python chybí hotový balíček. Nejčastěji jde o 32bitový Python nebo Windows na ARM, nainstaluj 64bitový (x64) Python. Případně zkus základní verzi `pip install -e .`. |
| `'daytrader' is not recognized…` | Není aktivované prostředí `.venv`. Aktivuj ho, nebo spusť `python -m daytrader dashboard`. |

Pokud nic z toho nesedí, pošli celý výpis chyby.

## Rychlý start

```bash
daytrader dashboard                 # webové rozhraní na http://localhost:8501
```

Nebo z příkazové řádky:

```bash
daytrader analyze AAPL                      # technický přehled (5min svíčky, 5 dní)
daytrader analyze CEZ.PR -i 15m -p 1mo      # ČEZ z pražské burzy
daytrader scan                              # scanner watchlistu (DT_WATCHLIST)
daytrader backtest NVDA -s orb -p 1mo       # backtest strategie ORB
daytrader optimize NVDA -s ema_cross -g fast=5,9,12 -g slow=21,30
daytrader buy AAPL                          # papírový nákup, velikost z rizika + stop z ATR
daytrader account                           # stav účtu a pozice
daytrader bot -s vwap_trend --symbols AAPL,MSFT --dry-run
daytrader journal                           # statistiky uzavřených obchodů
daytrader --help                            # všechny příkazy
```

Bez internetu nebo jen na vyzkoušení přidej `--provider demo` (případně `DT_DATA_PROVIDER=demo`
v `.env`). Použijí se generovaná data. Pro papírový účet jsou oddělená, takže se nemíchají se skutečnými cenami.

**Symboly:** americké akcie `AAPL`, `SPY`; pražská burza s příponou `.PR` (`CEZ.PR`, `KOMB.PR`,
`MONET.PR`); Xetra `.DE` (`SAP.DE`); krypto přes Yahoo `BTC-USD`, přes CCXT `BTC/USDT`.

---

## Napojení na API

Všechna nastavení jsou v souboru `.env` (vzor s komentáři je v `.env.example`).

### Yahoo Finance (výchozí zdroj dat)
Nic nenastavuješ. Intradenní historie je omezená: 1min svíčky za posledních 7 dní, 5–30min
svíčky za posledních 60 dní. Aplikace období sama zkrátí a upozorní na to.

### Alpaca (americké akcie, ETF a krypto)
1. Zaregistruj se na [alpaca.markets](https://alpaca.markets) a přepni se na **Paper Trading**.
2. Vygeneruj API klíče a vlož je do `.env`:
   ```ini
   ALPACA_API_KEY=...
   ALPACA_SECRET_KEY=...
   ALPACA_PAPER=true
   DT_BROKER=alpaca
   DT_DATA_PROVIDER=alpaca     # volitelné, jinak zůstanou data z Yahoo
   ```
3. `daytrader account` ověří spojení.

Alpaca podporuje **bracket příkazy**: stop-loss a take-profit hlídá server, i když máš počítač vypnutý.
U krypta (`BTC/USD`) je Alpaca nepovoluje, takže je hlídá bot a krypto tam jde jen nakupovat (bez shortu).
Bezplatná data IEX obsahují jen část celkového objemu trhu, takže VWAP a relativní objem jsou orientační.

### Kryptoburzy přes CCXT
```ini
CCXT_EXCHANGE=binance        # kraken, coinbase, bybit, okx, coinmate, …
CCXT_API_KEY=...
CCXT_SECRET=...
CCXT_SANDBOX=true            # testnet; klíče pro testnet se generují zvlášť
DT_BROKER=ccxt
```
Obchoduje se jen spotový trh, takže bez shortování. Stop-loss a take-profit u krypta hlídá bot.

### AI komentář (Claude API, placené)
Založ API klíč na [console.anthropic.com](https://console.anthropic.com) a vlož ho do `.env`:
```ini
ANTHROPIC_API_KEY=...
DT_AI_MODEL=claude-opus-5-5
DT_AI_EFFORT=medium          # low je levnější, high důkladnější
```
Pak použij `daytrader analyze AAPL --ai` nebo tlačítko v dashboardu. Odesílají se jen spočítané
indikátory a titulky zpráv, žádné údaje o účtu. Když model požadavek odmítne, API ho automaticky
zkusí na jiném doporučeném modelu (server-side fallback).

---

## Strategie

| Klíč | Název | Princip |
|---|---|---|
| `ema_cross` | Křížení EMA | Long, když je rychlá EMA nad pomalou, short naopak. |
| `vwap_trend` | VWAP trend | Long nad VWAP při rostoucích EMA, výstup pod VWAP. Jen intradenní. |
| `orb` | Průraz ranního rozpětí | Vstup při průrazu maxima nebo minima prvních N minut obchodování. Jen intradenní. |
| `rsi_reversion` | RSI návrat k průměru | Nákup při přeprodaném RSI, výstup při návratu ke středu. |
| `bollinger` | Bollinger návrat | Nákup pod dolním pásmem, výstup na středové linii. |
| `macd` | MACD momentum | Obchoduje křížení MACD a signální linie. |
| `scalp` | Skalpování | Minutové svíčky: v rostoucím trendu nákup po krátkém poklesu, prodej při odrazu, pod VWAP nebo nejpozději po 10 svíčkách. Jen intradenní. |

Parametry se mění přes `--param klic=hodnota` (např. `--param fast=5 --param slow=30`). Seznam vypíše `daytrader strategies`.
Žádná z nich není „hotový stroj na peníze“. Jsou to výchozí body pro vlastní testování.

## Jak číst backtest

- Signál se vyhodnotí na **zavření** svíčky a obchod proběhne na **otevření další**, takže backtest nevidí do budoucnosti.
- Stop-loss a take-profit se kontrolují uvnitř svíčky. Když by se v jedné svíčce trefily oba, počítá se konzervativně stop.
- **Profit factor** (hrubý zisk / hrubá ztráta) nad 1,3 je zajímavý, pod 1 je strategie ztrátová.
- **Max. propad** ukazuje, kolik bys musel(a) psychicky i finančně ustát.
- **R** je zisk v násobcích rizika. Průměrné R nad 0 znamená kladné očekávání.
- Méně než ~30 obchodů je statisticky slabý vzorek. Optimalizace parametrů vždy ověřuje výsledek na datech, která neviděla.
  Když tam výsledek výrazně zaostane, parametry jsou přeoptimalizované.

## Řízení rizik

Velikost pozice se počítá tak, aby zásah stop-lossu stál zhruba `DT_RISK_PER_TRADE_PCT` procent kapitálu:

```
množství = (kapitál × riziko %) / |vstup − stop-loss|     (max. DT_MAX_POSITION_PCT % kapitálu)
stop-loss = vstup ∓ DT_STOP_ATR_MULT × ATR(14)
take-profit = vstup ± DT_TAKE_PROFIT_R × vzdálenost stopu
```

Kontroly před každým novým obchodem: denní limit ztráty (`DT_MAX_DAILY_LOSS_PCT`), počet otevřených pozic,
počet obchodů za den, povinný stop-loss, kupní síla a povolení shortu (`DT_ALLOW_SHORT`, výchozí vypnuto).

## Automatické obchodování (bot)

Bot obchoduje sám. Výchozí je **papírový účet**, tedy falešné peníze bez rizika.

**Jak ho spustit (vyber si jednu cestu):**

1. **Dvojklik na `bot.bat`** (Windows). Bot běží v černém okně, dokud ho nezavřeš nebo nestiskneš Ctrl+C.
   Strategii, symboly a interval nastavíš v souboru `.env`:
   ```ini
   DT_BOT_STRATEGY=vwap_trend        # vwap_trend | orb | ema_cross | rsi_reversion | bollinger | macd | scalp
   DT_BOT_INTERVAL=5m
   DT_BOT_SYMBOLS=AAPL,MSFT,NVDA,AMD,TSLA
   DT_BOT_PARAMS=                    # např. fast=9,slow=21
   ```
2. **Dashboard → stránka *Bot*.** Vybereš symboly, strategii a parametry a klikneš na *Spustit bota*.
   Uvidíš stav, otevřené pozice a rozhodnutí. Bot běží, dokud běží dashboard.
3. **Příkazová řádka:** `daytrader bot` (bere nastavení z `.env`), případně
   `daytrader bot -s orb --symbols AAPL,MSFT -i 5m`. Volba `--dry-run` jen vypisuje rozhodnutí a nic neobchoduje.

**Co bot dělá:**
- Po uzavření každé svíčky vyhodnotí strategii. Vstupuje jen na **nový** signál a vystupuje, když se signál otočí.
- Každý obchod má stop-loss a take-profit z ATR. Velikost pozice a limity bere z nastavení rizika
  (1 % na obchod, max. 3 pozice, denní limit ztráty 3 %).
- 15 minut před koncem obchodování už neotevírá nové pozice a 5 minut před koncem všechny uzavře.
- Mimo obchodní hodiny čeká a každých 30 minut vypíše, kdy se trh otevře.
- Na jednom účtu smí běžet jen jeden bot. Druhý (např. současně z `bot.bat` i z dashboardu) se nespustí.
- Všechno zapisuje do deníku (stránka *Deník*, `daytrader journal`).

**Kde a kdy obchoduje** (náš čas; časová pásma i letní čas si bot hlídá sám):

| Trh | Symboly | Obchodní hodiny | Data z Yahoo |
|---|---|---|---|
| USA – NYSE, Nasdaq | `AAPL`, `MSFT`, `SPY` | po–pá 15:30–22:00* | v reálném čase |
| Burza cenných papírů Praha | `CEZ.PR`, `KOMB.PR`, `MONET.PR` | po–pá 9:00–16:20 | zpožděná o 20 min |
| Xetra (Frankfurt) | `SAP.DE`, `SIE.DE` | po–pá 9:00–17:30 | zpožděná |
| London Stock Exchange | `VOD.L`, `HSBA.L` | po–pá 9:00–17:30 | zpožděná |
| Krypto | `BTC-USD`, `ETH-USD` (přes CCXT `BTC/USDT`) | nonstop, i o víkendu | v reálném čase |

\* Na přelomu října a listopadu (asi týden) a v březnu (asi tři týdny) začíná o hodinu dřív,
protože USA mění čas v jiný den než Evropa.

U zpožděných dat bot vyhodnocuje jen svíčky, které jsou u zdroje už uzavřené, takže reaguje
o to zpoždění později. Na papírovém účtu to nevadí, na skutečné peníze to vhodné není.
Svátky bot nezná, ale pozná je podle toho, že nepřibývají nová data, a ten den neobchoduje.
Jiné burzy (např. Vídeň `.VI`, Varšava `.WA`, Paříž `.PA`) aplikace zatím nezná a bot by
u nich počítal s americkými hodinami, takže mu je nedávej. Krypto se hodí na vyzkoušení bota
i večer a o víkendu.

**Aby běžel každý den sám:** stiskni Win+R, napiš `shell:startup` a do otevřené složky vlož zástupce na `bot.bat`
(nebo na `bot-1min.bat`). Bot se pak spustí po každém přihlášení do Windows. Počítač nesmí během obchodních hodin usnout
(Nastavení → Systém → Napájení).

### Minutové obchodování (skalpování)

Bot se na trh dívá každou minutu a dělá krátké obchody na minutových svíčkách (strategie `scalp`):

- **Nákup** v rostoucím trendu (cena nad VWAP, EMA 20 nad EMA 50) po krátkém poklesu, když se RSI(5) vrátí nad 35.
- **Prodej**, jakmile RSI vyskočí na 65 (malý zisk), když cena zavře pod VWAP, nebo nejpozději po 10 minutách.
  Stop-loss a take-profit z ATR platí i tady.
- Na demo datech udělá zhruba 5–10 obchodů denně na jednu akcii a pozici drží v průměru asi 5 minut.

**Spuštění:** dvojklik na **`bot-1min.bat`** (symboly bere z `DT_BOT_SYMBOLS`, nejvýš 100 obchodů za den),
v dashboardu strategie *Skalpování* (interval se přepne na 1 minutu a limit obchodů na 100), nebo
`daytrader bot -s scalp -i 1m --max-trades 100`. Parametry: např. `--param max_hold=5 --param dip=30`,
jejich popis vypíše `daytrader strategies`.

**Co je dobré vědět:**
- Víc obchodů neznamená víc zisku. Každý obchod stojí spread a skluz a u minutových obchodů jsou zisky tak malé,
  že z nich tyhle náklady ukousnou velký kus. Papírový účet počítá se skluzem 0,02 % na každý nákup i prodej
  (`DT_PAPER_SLIPPAGE_BPS`).
- Nejdřív si strategii vyzkoušej v backtestu na skutečných datech: `daytrader backtest AAPL -s scalp -i 1m -p 7d`
  (Yahoo dává minutová data jen za posledních 7 dní) a pak aspoň pár týdnů na papírovém účtu.
- Hodí se pro likvidní americké akcie a ETF (AAPL, NVDA, SPY, QQQ…) a pro krypto. Pražská burza má data
  o 20 minut zpožděná a málo obchodů, minutové obchodování tam nedává smysl.
- Stop-loss na minutových svíčkách je blízko, takže velikost pozice omezí limit 25 % kapitálu (`DT_MAX_POSITION_PCT`)
  a skutečné riziko na obchod bývá menší než 1 %.
- Kryptoburzy si berou poplatek zhruba 0,1–0,6 % z každého obchodu, což minutové obchody na skutečném účtu
  většinou prodělá. Americké pravidlo PDT (minimálně 25 000 USD na účtu pro častý day trading) regulátor
  od 4. 6. 2026 zrušil, brokeři ho ale můžou rušit postupně až do října 2027. Ověř si, jak to má tvůj broker.
- Bot stahuje data každou minutu. Dotazy na Yahoo proto slučuje (jedno stažení na symbol za kolo),
  ale s desítkami symbolů může Yahoo začít požadavky dočasně odmítat.

## Přechod na živé obchodování

1. Obchoduj **alespoň několik týdnů na papírovém účtu** a sleduj deník (úspěšnost, profit factor, propady).
2. Začni s malou částkou a rizikem ≤ 1 % na obchod.
3. V `.env` nastav `DT_LIVE_TRADING=true` a u Alpaca `ALPACA_PAPER=false` s live klíči (u CCXT `CCXT_SANDBOX=false`).
4. Každý živý příkaz v příkazové řádce potvrzuješ napsáním `ANO`. Živého bota lze spustit jen z příkazové řádky.

**Daně:** zisky z obchodování jsou v ČR příjmem, který se daní. Osvobození (časový test 3 roky, limit příjmů z prodeje
100 000 Kč za rok) se na aktivní day trading obvykle nevztahuje. Export z deníku (CSV) je podklad pro přiznání.
Konkrétní situaci konzultuj s daňovým poradcem.

---

## Struktura projektu

```
src/daytrader/
├── analysis/      indikátory, úrovně, technický přehled
├── strategies/    obchodní strategie (signály −1/0/1)
├── backtest/      backtester a metriky
├── data/          zdroje dat: Yahoo, Alpaca, CCXT, demo
├── brokers/       brokeři: papírový účet (SQLite), Alpaca, CCXT
├── dashboard/     webové rozhraní (Streamlit + Plotly)
├── risk.py        velikost pozice a kontroly rizika
├── trading.py     plán a provedení ručního příkazu
├── bot.py         automatický obchodní bot
├── journal.py     deník a statistiky obchodů
├── scanner.py     scanner watchlistu
├── ai.py          AI komentář (Claude API)
└── cli.py         příkazová řádka
```

**Rozšíření:** nový broker (např. Interactive Brokers nebo Trading 212) implementuje rozhraní
`brokers/base.py:Broker`. Nová strategie dědí z `strategies/base.py:Strategy` a přidá se do `STRATEGIES`.

## Vývoj a testy

```bash
pip install -e ".[dev]"
pytest
```

Testy běží offline: používají generovaná data a simulované odpovědi API (Alpaca, CCXT, Yahoo, Claude).
