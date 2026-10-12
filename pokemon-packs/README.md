# Booster Lab – simulátor otevírání balíčků Pokémon TCG

Webová aplikace (PWA), která jde nainstalovat na Android i Windows. Obsahuje skutečné sady
a karty Pokémon TCG, šance na tah podle reálných měření a tržní ceny karet.

## Co umí

- **Obchod**: posledních 10 vydaných sad. Balíčky jsou zdarma po jednom, po deseti nebo jako booster box (36).
  U každé sady je tabulka **šancí na tah** se složením balíčku a odkazy na zdroje.
- **Skutečné obaly a rub karet**: fotky booster packů každé sady (katalog TCGplayer) a oficiální rub
  karty Pokémon TCG. Když se obrázek nenačte, použije se náhradní potisk.
- **Otevírání ve 3D**: balíček má přední a zadní stranu i boky, pohupuje se a naklání podle prstu, myši
  nebo náklonu telefonu; tažením ho jde otočit. Roztrhneš ho tažením přes horní okraj (nebo klepnutím),
  horní pruh odletí a karty vyjedou z balíčku jako 3D balík. Kartu odhodíš klepnutím nebo tažením do strany.
  Poslední tři karty jsou lícem dolů a otáčejí se ve 3D; vzácná karta se předtím rozzáří barvou rarity
  a vybuchne částicemi, u SIR a zlatých karet navíc problikne obrazovka. Jde i otevřít bez animace
  nebo všechny balíčky naráz.
- **Holo efekty**: lesk podle rarity (holo, duhový, zlatý, Black White) a reverse holo včetně vzorů
  Poké Ball / Master Ball. Reaguje na myš, prst i náklon telefonu.
- **Album**: přehled všech sad s procentem kompletnosti. Album sady zobrazuje všechny karty
  (chybějící zašedle), počet kusů (×N), provedení (RH, PB, MB) a cenu. Filtry Vše / Mám / Chybí / Duplikáty,
  filtr rarity, hledání a řazení podle čísla, rarity, jména, ceny nebo počtu kusů.
- **Detail karty**: velký obrázek s holo efektem, počty podle provedení a duplikáty, datum prvního získání
  a ceny z Cardmarket (EUR) a TCGplayer (USD) s odkazy.
- **Hodnota sbírky** podle aktuálních cen, **záloha** sbírky do souboru a obnovení na jiném zařízení.
- Funguje **offline**: data sad jsou součástí aplikace, obrázky karet se po prvním zobrazení ukládají.

## Spuštění

Potřebuješ Node.js 20+.

```bash
cd pokemon-packs
npm install
npm run dev        # vývojový server na http://localhost:5173
npm test           # testy generátoru balíčků
npm run build      # produkční build do dist/
npm run preview    # náhled buildu (včetně service workeru)
```

### Instalace jako aplikace

Aplikace musí běžet přes HTTPS (nebo na `localhost`). Nejjednodušší je GitHub Pages:
v repozitáři zapni **Settings → Pages → Source: GitHub Actions**. Workflow
`.github/workflows/pokemon-packs.yml` ji pak nasadí po každém pushi do výchozí větve,
případně ji spustíš ručně (Actions → pokemon-packs → Run workflow).

- **Android (Chrome)**: otevři adresu → menu ⋮ → *Přidat na plochu / Instalovat aplikaci*.
- **Windows (Edge / Chrome)**: ikona instalace v adresním řádku → *Instalovat*.

## Data

| Co | Odkud | Kdy se aktualizuje |
|---|---|---|
| Sady a karty | [PokemonTCG/pokemon-tcg-data](https://github.com/PokemonTCG/pokemon-tcg-data) (stejná data jako Pokémon TCG API) | při spuštění `npm run data` |
| Obrázky karet | CDN Pokémon TCG API / Scrydex | načítají se za běhu |
| Fotky obalů | CDN TCGplayer (ID produktů „Booster Pack“ v `src/ui/pack.ts`, z exportu katalogu na [tcgcsv.com](https://tcgcsv.com)) | načítají se za běhu |
| Rub karty | tcg.pokemon.com | načítá se za běhu |
| Ceny | [TCGdex](https://tcgdex.dev) (Cardmarket + TCGplayer) přibalené při buildu (`npm run prices`, CI denně); chybějící sady živě z [Pokémon TCG API](https://pokemontcg.io), v detailu karty živě z TCGdex | build + za běhu (12 h cache) |
| Šance na tah | TCGplayer Authentication Center a komunitní statistiky, viz `src/odds.ts` | ručně |

`npm run data` stáhne 10 nejnovějších sad (počet jde změnit: `npm run data -- 15`). Podsada
*Classic Collection* z 30th Celebration je sloučená do své hlavní sady, protože padá ve stejných balíčcích.
Pro novou sadu je potřeba doplnit profil balíčku do `src/odds.ts`, jinak se použijí průměrné šance
éry Mega Evolution. Test `npm test` ověří, že každá rarita v profilu v datech sady existuje.

### Jak se losuje balíček

Každý slot balíčku (`src/odds.ts`) má výchozí raritu a seznam vzácných výsledků se šancí na balíček.
Například standardní balíček Scarlet & Violet / Mega Evolution: 4× Common, 3× Uncommon, reverse holo,
druhý reverse holo slot (může být Illustration Rare, SIR nebo zlatá karta) a Rare slot (Rare, Double Rare,
Ultra Rare). Konkrétní karta se pak vybírá rovnoměrně ze všech karet dané rarity.
Pokémon šance oficiálně nezveřejňuje, jde o naměřené průměry. U novějších sad a vzácností
s malým vzorkem (Black White Rare, Chaos Rising) jsou to odhady, poznámka u sady to uvádí.

## Struktura

```
pokemon-packs/
├── public/data/        karty a sady (JSON, generuje scripts/fetch-data.mjs)
├── public/sw.js        service worker (offline, cache obrázků)
├── src/odds.ts         rarity, složení balíčků, šance a zdroje
├── src/pack.ts         generátor balíčků (+ pack.test.ts)
├── src/store.ts        sbírka a neotevřené balíčky v localStorage
├── src/prices.ts       ceny z Pokémon TCG API / TCGdex
└── src/views/          obchod, otevírání, album, detail karty, nastavení
```

## Upozornění

Neoficiální fanouškovský projekt pro soukromé použití, bez reklam a bez prodeje. Pokémon,
názvy karet a ilustrace patří společnostem Nintendo, Creatures, GAME FREAK a The Pokémon Company.
Aplikaci proto nepublikuj do obchodů s aplikacemi a nezpeněžuj ji.
