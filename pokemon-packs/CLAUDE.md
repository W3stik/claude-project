# Booster Lab (pokemon-packs) – poznámky pro agenta

Fanouškovská PWA (Android i Windows přes „Instalovat aplikaci“), ve které si uživatel zdarma bere
a otevírá balíčky **skutečných** sad Pokémon TCG a sbírá karty do alba. Uživatel komunikuje česky,
celé UI i komentáře jsou česky. Návod pro uživatele je v `README.md`, kořenové pokyny pro celý
repozitář v `../CLAUDE.md`.

## Příkazy

```bash
npm install
npm run dev        # vývojový server http://localhost:5173
npm test           # Vitest (src/pack.test.ts): data, šance, generátor, regál – 11 testů
npm run build      # tsc --noEmit + vite build → dist/  (vždy před commitem)
npm run e2e        # Playwright průchod celou aplikací nad buildem, snímky v e2e-shots/
                   # (poprvé: npx playwright install chromium); obrázky a API podvrhuje
npm run data       # stáhne 10 nejnovějších sad do public/data (npm run data -- 15 = 15 sad)
npm run prices     # ceny z TCGdex → public/data/prices.json (gitignored, dělá to CI)
```

Bez frameworku: DOM se staví helperem `h()` z `src/ui/dom.ts`. Routing je hash (`#/shop`,
`#/pick/:setId`, `#/open[/:setId]`, `#/album[/:setId]`, `#/more`) v `src/main.ts`.
Každá obrazovka se kreslí do nového kontejneru (pomalé načítání staré obrazovky nepřepíše novou).

## Mapa kódu

| Soubor | Co dělá |
|---|---|
| `scripts/fetch-data.mjs` | Stáhne sady a karty z GitHubu `PokemonTCG/pokemon-tcg-data` (stejná data jako Pokémon TCG API). Bere 10 nejnovějších booster sad (bez promo apod.), zahodí karty s nečíselným číslem. **Podsady** (`SUBSETS`, nyní `me55c` Classic Collection) slučuje do hlavní sady s raritou „Classic Collection“, prefixem `CC` a přečíslováním 1–30. `MEGA_ATTACK_RARE` přejmenuje na „Mega Attack Rare“. |
| `public/data/*.json` | Commitnutá data: `sets.json` + jeden soubor na sadu (zmenšené karty: id, jméno, číslo, rarita, typy, obrázky). |
| `scripts/fetch-prices.mjs` | Ceny z TCGdex pro všechny karty → `public/data/prices.json` (`{updated, source, cards: {id: {eur, eurReverse, usd, usdReverse}}}`). Sady páruje podle jména, karty podle čísla. Běží v CI před buildem. |
| `src/odds.ts` | **Rarity** (`RARITIES`: pořadí, barva, typ lesku, zda je to „hit“) a **profily balíčků** (`PACKS`): sloty, šance a zdroje pro každou sadu. `DEFAULT_PACK` pro sadu bez profilu. |
| `src/pack.ts` | `openPack(profile, pools, rng)` – v každém slotu losuje vzácné výsledky podle šance, jinak výchozí raritu; bez opakování karty+provedení v balíčku. `toSealed/fromSealed` (uložitelná podoba balíčku), `hintLevel` (síla tajného náznaku). |
| `src/store.ts` | Stav hry v `localStorage` pod klíčem `pokemon-packs:state:v1`: `packs` (počty neotevřených), `collection` (klíč `idKarty|provedení` → kusy), `firstSeen`, `opened`, `history`, `shelf` (regál 10 balíčků na sadu), `sealed` (vybrané balíčky s daným obsahem, jsou součástí `packs`). Export/import zálohy. |
| `src/prices.ts` | Ceny: 1) `data/prices.json` z buildu, 2) živě Pokémon TCG API po sadách (s opakováním při 5xx, cache 12 h v localStorage), 3) `tcgdexPrice` živě pro jednu kartu v detailu. |
| `src/data.ts` | Načítání `sets.json` a karet sady (cache), `setIdOfCard`, `cardNumber`. |
| `src/views/shop.ts` | Obchod: „1 balíček“ vede na regál, „10 balíčků“ a „Booster box (36)“ přidají balíčky naslepo; okno „Šance a zdroje“. |
| `src/views/pick.ts` | Regál: 10 předem vylosovaných balíčků (uložené ve `state.shelf`, obnovení stránky je nepřelosuje). Vzatý balíček jde do `sealed` a jeho místo zaplní nový. Balíček s IR/UR a vzácnější kartou má **tajnou jiskřičku** (`hintLevel` 1–3). |
| `src/views/open.ts` | Otevírání: 3D balíček (tažení přes horní pruh = roztržení, jinde = otáčení, klepnutí = roztržení) → karty vyjedou jako 3D balík lícem nahoru → klepnutím/tažením se odhazují → přehled. Vybraný balíček z regálu se otevře s uloženým obsahem (`nextSealed`). Vzácná karta se při odkrytí rozzáří (`revealHit`: burst, u SIR+ záblesk). „Otevřít vše“ seskupuje stejné karty. |
| `src/views/album.ts` | Přehled sad (kompletnost, duplikáty, hodnota) a album sady (filtry, rarita, hledání, řazení podle čísla/rarity/jména/ceny/počtu). |
| `src/views/cardModal.ts` | Detail karty: 3D prohlížeč, počty podle provedení, ceny, celoobrazovkový režim. |
| `src/ui/pack.ts` | 3D model balíčku (`packEl`), ID produktů TCGplayer (`PACK_PRODUCTS`) a URL fotek, jiskřička náznaku. |
| `src/ui/holo.ts` | 2D karta s holo vrstvami (`cardEl`), naklánění kurzorem/gyroskopem (`enableTilt`), rub karty (`cardBack`, oficiální obrázek + náhradní design), `preload`. |
| `src/ui/card3d.ts` | 3D model karty (líc, rub, hrany) a prohlížeč s tažením, setrvačností, otočením a gyroskopem. |
| `public/sw.js` | Service worker: app shell a data offline (data network-first), obrázky karet/obalů/rubu cache-first přes CORS (opaque odpovědi se neukládají kvůli kvótě). Při změně cachovaných cest zvyš `VERSION`. |

## Data a externí zdroje (co je ověřené)

Ověřováno 12. 10. 2026 z GitHub Actions (sandbox, kde aplikace vznikla, měl na tyto hosty zakázaný přístup):

| Zdroj | Stav |
|---|---|
| `raw.githubusercontent.com/PokemonTCG/pokemon-tcg-data` | funguje, data až po 30th Celebration (září 2026) |
| Obrázky karet `images.pokemontcg.io`, `images.scrydex.com` | 200, CORS `*` |
| Fotky obalů `tcgplayer-cdn.tcgplayer.com/product/{id}_in_1000x1000.jpg` / `_400w.jpg` | 200, CORS `*`; fotky jsou těsně oříznuté (bez bílého okraje), poměr ~0,5–0,55 |
| Rub karty `tcg.pokemon.com/assets/img/global/tcg-card-back-2x.jpg` | 200, **bez CORS** → zobrazí se, ale service worker ho offline neuloží |
| `api.pokemontcg.io/v2/cards` | **nespolehlivé** – střídavě 200 a 500 (projekt přechází na placený Scrydex) |
| TCGdex `api.tcgdex.net/v2/en` | funguje, CORS `*`; ceny má pro 9 z 10 sad, **30th Celebration (me55) zatím bez cen** |
| `tcgcsv.com` (export katalogu TCGplayer) | funguje, vyžaduje vlastní `User-Agent`; odtud jsou ID produktů v `PACK_PRODUCTS` |

ID sad TCGdex: sv10, sv10.5b, sv10.5w, me01, me02, me02.5, me03, me04, me05, 30th.

**Šance na tah** nejsou oficiální. Jsou to měření TCGplayer a komunitní statistiky, zdroje a poznámky
jsou přímo u každého profilu v `src/odds.ts` a zobrazují se v aplikaci. Odhady: Chaos Rising (SIR, MHR),
Black White Rare (1:1789), část 30th Celebration.

### Přidání nové sady

1. `npm run data` (nebo s vyšším počtem). Když sada má podsadu prodávanou ve stejných balíčcích,
   přidej ji do `SUBSETS` ve `scripts/fetch-data.mjs`.
2. Do `PACKS` v `src/odds.ts` přidej profil (sloty, šance, barvy, zdroje). Nové rarity přidej do `RARITIES`.
3. Do `PACK_PRODUCTS` v `src/ui/pack.ts` přidej productId „{Sada} Booster Pack“ z
   `https://tcgcsv.com/tcgplayer/3/groups` → `/{groupId}/products` (hlavička `User-Agent`).
4. `npm test` ověří, že každá rarita z profilu v datech existuje a obráceně, a že součty šancí < 1.

## Nasazení

Workflow `../.github/workflows/pokemon-packs.yml`: test → `npm run prices` (smí selhat) → build →
artefakt → **deploy na GitHub Pages jen z výchozí větve** (push, denní cron 5:17 UTC kvůli cenám,
ruční spuštění). Předpoklad: *Settings → Pages → Source: GitHub Actions*. Výchozí větev repozitáře je
`claude/day-trading-app-66jnnu`; Booster Lab je zatím jen ve větvi `claude/awesome-cori-5nrn80`
(nesloučeno, bez PR). Vite má `base: "./"`, takže build funguje v podsložce Pages.

## Nástrahy (naučené na vlastní kůži)

- **3D v CSS**: přidané roviny uvnitř `preserve-3d` (např. „jádro“ karty mezi lícem a rubem) se
  v balíčku karet protínaly s ostatními kartami a vykukovaly jako světlé obdélníky. Proto karty
  v balíčku při otevírání **nemají hranu**; hrany má jen samostatná karta v prohlížeči (`card3d.ts`).
- Boky balíčku berou barvu z okraje fotky (`background: var(--art) … / 4000% 100%`), ne z barev sady –
  jinak při pohupování svítí barevné pruhy. Boky se k zataveným okrajům zaoblují (`clip-path: inset(… round 999px)`).
- Odtrhávací pruh a zbytek obalu jsou dvě kopie stejné fotky s `clip-path`; pruh má malý přesah,
  jinak je mezi díly vlasová spára.
- `calc(var(--x) / 1deg)` (dělení jednotkou) starší prohlížeče neumí – nepoužívat.
- `filter`/`box-shadow` na ploše s `clip-path` se ořízne; zvýraznění dávej na nadřazený prvek.
- Zvýraznění řezu (`.pack3d__cut`) má `box-shadow` – při nulové délce musí mít `opacity: 0`, jinak svítí tečka.
- Animace s `animation-delay` měněnou za běhu nejdou spolehlivě „zmrazit“ pro snímek; v testech
  raději animaci vypni (`animation: none`) a nastav stav natvrdo.
- Esc v celoobrazovkovém prohlížeči se zachytává ve fázi capture, aby nezavřel i detail pod ním.

## Konvence

- Texty UI, komentáře a hlášky česky; názvy rarit a sad anglicky (oficiální).
- Stav hry měň jen přes funkce ze `store.ts` (ukládají a volají posluchače). Při nekompatibilní
  změně schématu zvyš verzi klíče a doplň migraci (`load()` dnes doplňuje chybějící pole z `empty()`).
- Žádné reklamy ani zpoplatnění: obrázky a jména patří Nintendo / The Pokémon Company; projekt je
  soukromý fanouškovský (upozornění v `README.md` a v sekci Více).

## Nápady na další práci (neudělané)

Seřazeno podle přínosu:

1. Sloučit větev do výchozí a zapnout GitHub Pages → aplikace jde nainstalovat na telefon.
2. Zvuky (trhání, odhození, fanfára u vzácné karty) a vibrace (`navigator.vibrate`) při hitu.
3. „God pack“ (vzácný balíček plný IR/SIR) u sad, kde existuje (Ascended Heroes), jako samostatný výsledek v profilu.
4. Herní ekonomika: prodej duplikátů za mince podle tržní ceny, nákup balíčků za mince.
5. „Master set“ v albu: kompletnost včetně reverse/Poké Ball/Master Ball provedení; statistiky nejlepších tahů a historie hodnoty sbírky.
6. Synchronizace sbírky mezi zařízeními (dnes jen ruční záloha do souboru).
7. Starší sady / automatická kontrola nových sad v CI (nová sada bez profilu v `PACKS` použije `DEFAULT_PACK`).
8. Virtualizace mřížky alba pro velké sady (Ascended Heroes má 295 karet) a `npm run e2e` v CI.
