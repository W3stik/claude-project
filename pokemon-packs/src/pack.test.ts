import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";
import { PACKS, oddsTable, packProfile, packSize, rarityInfo, RARITIES } from "./odds";
import { byRarity, fromSealed, hintLevel, openPack, toSealed } from "./pack";
import { getState, nextSealed, pickFromShelf, recordOpening, resetState, setShelf } from "./store";
import type { Card, SetInfo } from "./types";

const dataDir = new URL("../public/data/", import.meta.url);
const sets: SetInfo[] = JSON.parse(readFileSync(new URL("sets.json", dataDir), "utf8"));
const cardsOf = (id: string): Card[] => JSON.parse(readFileSync(new URL(`${id}.json`, dataDir), "utf8"));

/** Deterministický generátor (mulberry32), aby testy nebyly náhodné. */
function seeded(seed: number) {
  return () => {
    seed = (seed + 0x6d2b79f5) | 0;
    let t = Math.imul(seed ^ (seed >>> 15), 1 | seed);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

describe("data a konfigurace šancí", () => {
  it("obsahuje 10 sad a každá má profil balíčku", () => {
    expect(sets).toHaveLength(10);
    for (const set of sets) expect(PACKS[set.id], set.id).toBeDefined();
  });

  it("každá rarita v profilu existuje v datech sady a naopak má každá karta známou raritu", () => {
    for (const set of sets) {
      const pools = byRarity(cardsOf(set.id));
      for (const slot of packProfile(set.id).slots) {
        for (const outcome of [slot.base, ...slot.hits]) {
          const size = outcome.rarities.reduce((n, r) => n + (pools.get(r)?.length ?? 0), 0);
          expect(size, `${set.id}: ${outcome.rarities.join("/")}`).toBeGreaterThan(0);
        }
      }
      for (const rarity of pools.keys()) expect(RARITIES[rarity], `${set.id}: ${rarity}`).toBeDefined();
    }
  });

  it("součet šancí ve slotu nepřesáhne 100 %", () => {
    for (const [id, profile] of Object.entries(PACKS)) {
      for (const slot of profile.slots) {
        const sum = slot.hits.reduce((n, h) => n + (h.p ?? 0), 0);
        expect(sum, `${id}: ${slot.label}`).toBeLessThan(1);
      }
    }
  });

  it("tabulka šancí řadí od nejčastější", () => {
    const rows = oddsTable(packProfile("me1"));
    expect(rows[0].label).toBe("Double Rare");
    expect(rows.at(-1)?.label).toBe("Mega Hyper Rare");
  });
});

describe("otevírání balíčků", () => {
  it("standardní balíček má 10 karet a správné složení", () => {
    const pools = byRarity(cardsOf("me1"));
    const pack = openPack(packProfile("me1"), pools, seeded(1));
    expect(pack).toHaveLength(10);
    expect(pack.slice(0, 4).every((p) => p.card.rarity === "Common")).toBe(true);
    expect(pack.slice(4, 7).every((p) => p.card.rarity === "Uncommon")).toBe(true);
    expect(pack[7].variant).toBe("reverse");
    expect(rarityInfo(pack[9].card.rarity).rank).toBeGreaterThanOrEqual(rarityInfo("Rare").rank);
  });

  it("30th Celebration má 5 karet a poslední je vždy Pikachu Rare", () => {
    const pools = byRarity(cardsOf("me55"));
    const rng = seeded(7);
    for (let i = 0; i < 200; i++) {
      const pack = openPack(packProfile("me55"), pools, rng);
      expect(pack).toHaveLength(packSize(packProfile("me55")));
      expect(pack.at(-1)?.card.rarity).toBe("Pikachu Rare");
    }
  });

  it("v balíčku se neopakuje stejná karta ve stejném provedení", () => {
    const pools = byRarity(cardsOf("sv10"));
    const rng = seeded(3);
    for (let i = 0; i < 500; i++) {
      const keys = openPack(packProfile("sv10"), pools, rng).map((p) => `${p.card.id}|${p.variant}`);
      expect(new Set(keys).size).toBe(keys.length);
    }
  });

  it("vzácný výsledek bez karet v sadě dá výchozí raritu, ne další vzácný výsledek", () => {
    const pools = byRarity(cardsOf("me1"));
    const profile = {
      colors: ["#000", "#fff"] as [string, string],
      sources: [],
      slots: [
        {
          label: "Test",
          count: 1,
          hits: [
            { rarities: ["Neexistující"], variant: "normal" as const, p: 0.5 },
            { rarities: ["Rare"], variant: "normal" as const, p: 0.5 },
          ],
          base: { rarities: ["Common"], variant: "normal" as const },
        },
      ],
    };
    const rolls = [0.3, 0];
    const pack = openPack(profile, pools, () => rolls.shift() ?? 0);
    expect(pack[0].card.rarity).toBe("Common");
  });

  it("četnost rarit odpovídá nastaveným šancím", () => {
    const profile = packProfile("me2");
    const pools = byRarity(cardsOf("me2"));
    const rng = seeded(42);
    const n = 100_000;
    const counts = new Map<string, number>();
    for (let i = 0; i < n; i++) {
      for (const { card } of openPack(profile, pools, rng)) {
        counts.set(card.rarity, (counts.get(card.rarity) ?? 0) + 1);
      }
    }
    const rate = (r: string) => (counts.get(r) ?? 0) / n;
    expect(rate("Double Rare")).toBeCloseTo(0.2077, 2);
    expect(rate("Illustration Rare")).toBeCloseTo(0.1097, 2);
    expect(rate("Ultra Rare")).toBeCloseTo(0.0806, 2);
    expect(rate("Special Illustration Rare")).toBeCloseTo(0.0125, 2);
  });
});

describe("regál a předem určené balíčky", () => {
  const cards = cardsOf("me1");
  const pools = byRarity(cards);
  const byId = new Map(cards.map((c) => [c.id, c]));

  it("uložený balíček se obnoví na stejné karty", () => {
    const pack = openPack(packProfile("me1"), pools, seeded(5));
    expect(fromSealed(toSealed(pack), byId)).toEqual(pack);
    expect(fromSealed({ cards: [{ id: "neexistuje-1", variant: "normal" }] }, byId)).toBeNull();
  });

  it("náznak odpovídá nejvzácnější kartě v balíčku", () => {
    const of = (rarity: string) => [{ card: cards.find((c) => c.rarity === rarity)!, variant: "normal" as const }];
    expect(hintLevel(of("Double Rare"))).toBe(0);
    expect(hintLevel(of("Illustration Rare"))).toBe(1);
    expect(hintLevel(of("Ultra Rare"))).toBe(1);
    expect(hintLevel(of("Special Illustration Rare"))).toBe(2);
    expect(hintLevel(of("Mega Hyper Rare"))).toBe(3);
  });

  it("vybraný balíček z regálu se otevře jako první a jeho místo zaplní nový", () => {
    resetState();
    const shelf = Array.from({ length: 10 }, (_, i) => toSealed(openPack(packProfile("me1"), pools, seeded(100 + i))));
    setShelf("me1", shelf);
    const replacement = toSealed(openPack(packProfile("me1"), pools, seeded(999)));
    pickFromShelf("me1", 3, replacement);

    expect(getState().packs.me1).toBe(1);
    expect(nextSealed("me1")).toEqual(shelf[3]);
    expect(getState().shelf.me1[3]).toEqual(replacement);

    recordOpening("me1", fromSealed(shelf[3], byId)!);
    expect(getState().packs.me1).toBeUndefined();
    expect(nextSealed("me1")).toBeUndefined();
  });
});
