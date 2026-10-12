// Stáhne seznam sad a karty nejnovějších sad z otevřeného repozitáře
// PokemonTCG/pokemon-tcg-data (stejná data, jaká vrací api.pokemontcg.io)
// a uloží je zmenšené do public/data. Spouští se ručně: npm run data [počet]
import { mkdir, writeFile } from "node:fs/promises";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const RAW = "https://raw.githubusercontent.com/PokemonTCG/pokemon-tcg-data/master";
const OUT = join(dirname(fileURLToPath(import.meta.url)), "..", "public", "data");
const COUNT = Number(process.argv[2] ?? 10);

async function getJson(url) {
  const res = await fetch(url);
  if (!res.ok) throw new Error(`${url}: HTTP ${res.status}`);
  return res.json();
}

// Promo sady a podobné produkty se v booster balíčcích neprodávají.
const isBoosterSet = (s) => !/promo|energies|trainer kit|mcdonald/i.test(s.name);

// Podsady, které se prodávají v balíčcích jiné sady (podsada → hlavní sada).
const SUBSETS = { me55c: { parent: "me55", label: "Classic Collection", prefix: "CC" } };

const allSets = await getJson(`${RAW}/sets/en.json`);
const sets = allSets
  .filter((s) => isBoosterSet(s) && !SUBSETS[s.id])
  .sort((a, b) => b.releaseDate.localeCompare(a.releaseDate))
  .slice(0, COUNT);

await mkdir(OUT, { recursive: true });

const slimCard = (c) => ({
  id: c.id,
  name: c.name,
  number: Number(c.number),
  rarity: c.rarity === "MEGA_ATTACK_RARE" ? "Mega Attack Rare" : c.rarity,
  supertype: c.supertype,
  subtypes: c.subtypes ?? [],
  types: c.types ?? [],
  hp: c.hp ?? null,
  artist: c.artist ?? null,
  img: c.images.small,
  imgLarge: c.images.large,
});

const index = [];
for (const set of sets) {
  const cards = await getJson(`${RAW}/cards/en/${set.id}.json`);
  const slim = cards
    // Karty s nečíselným číslem (např. R/G/B varianty) se v balíčcích nevyskytují.
    .filter((c) => /^\d+$/.test(c.number) && c.rarity)
    .map(slimCard)
    .sort((a, b) => a.number - b.number);

  // Reprinty z podsady mají původní čísla ze starých sad, proto je přečíslujeme
  // podle pořadí (CC1–CC30) a původní raritu si necháme jen pro zobrazení.
  for (const [subId, sub] of Object.entries(SUBSETS)) {
    if (sub.parent !== set.id) continue;
    const subCards = await getJson(`${RAW}/cards/en/${subId}.json`);
    subCards.forEach((c, i) =>
      slim.push({
        ...slimCard(c),
        number: i + 1,
        prefix: sub.prefix,
        rarity: sub.label,
        printedRarity: c.rarity ?? null,
      }),
    );
  }

  await writeFile(join(OUT, `${set.id}.json`), JSON.stringify(slim));
  index.push({
    id: set.id,
    name: set.name,
    series: set.series,
    code: set.ptcgoCode ?? null,
    releaseDate: set.releaseDate.replaceAll("/", "-"),
    printedTotal: set.printedTotal,
    total: slim.length,
    logo: set.images.logo,
    symbol: set.images.symbol,
  });
  console.log(`${set.id.padEnd(10)} ${set.name.padEnd(22)} ${slim.length} karet`);
}

await writeFile(join(OUT, "sets.json"), JSON.stringify(index, null, 1));
console.log(`Hotovo: ${index.length} sad v ${OUT}`);
