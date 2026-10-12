// Stáhne aktuální tržní ceny všech karet z TCGdex (Cardmarket v EUR,
// TCGplayer v USD) a uloží je do public/data/prices.json, aby je aplikace
// měla hned a i offline. Spouští se v CI před buildem: npm run prices
import { readFile, writeFile } from "node:fs/promises";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { parseTcgdexPricing } from "../src/tcgdexPricing.js";

const API = "https://api.tcgdex.net/v2/en";
const DATA = join(dirname(fileURLToPath(import.meta.url)), "..", "public", "data");
const CONCURRENCY = 8;

async function getJson(url, tries = 3) {
  for (let i = 1; ; i++) {
    try {
      const res = await fetch(url);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      return await res.json();
    } catch (err) {
      if (i >= tries) throw new Error(`${url}: ${err.message}`);
      await new Promise((r) => setTimeout(r, 500 * i));
    }
  }
}

async function pool(items, fn) {
  const results = [];
  let next = 0;
  await Promise.all(
    Array.from({ length: CONCURRENCY }, async () => {
      while (next < items.length) {
        const i = next++;
        results[i] = await fn(items[i]).catch(() => undefined);
      }
    }),
  );
  return results;
}

const sets = JSON.parse(await readFile(join(DATA, "sets.json"), "utf8"));
const tcgdexSets = await getJson(`${API}/sets`);
const cards = {};

for (const set of sets) {
  const remote = tcgdexSets.find((s) => s.name.toLowerCase() === set.name.toLowerCase());
  if (!remote) {
    console.warn(`${set.id}: sada „${set.name}“ v TCGdex není`);
    continue;
  }
  const ours = JSON.parse(await readFile(join(DATA, `${set.id}.json`), "utf8")).filter((c) => !c.prefix);
  const byNumber = new Map(ours.map((c) => [c.number, c.id]));
  const { cards: list } = await getJson(`${API}/sets/${remote.id}`);
  const wanted = list.filter((c) => byNumber.has(Number(c.localId)));
  const details = await pool(wanted, (c) => getJson(`${API}/cards/${c.id}`));

  let priced = 0;
  wanted.forEach((c, i) => {
    const price = parseTcgdexPricing(details[i]?.pricing);
    if (Object.keys(price).length) {
      cards[byNumber.get(Number(c.localId))] = price;
      priced++;
    }
  });
  console.log(`${set.id.padEnd(10)} ${remote.id.padEnd(8)} ${priced}/${ours.length} karet s cenou`);
}

const out = { updated: new Date().toISOString(), source: "tcgdex", cards };
await writeFile(join(DATA, "prices.json"), JSON.stringify(out));
console.log(`Uloženo ${Object.keys(cards).length} cen do public/data/prices.json`);
