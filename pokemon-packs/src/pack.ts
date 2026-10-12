import { type Outcome, type PackProfile } from "./odds";
import type { Card, PulledCard } from "./types";

export type Rng = () => number;

/** Rozdělí karty sady podle rarity, aby se losovalo rychle. */
export function byRarity(cards: Card[]): Map<string, Card[]> {
  const map = new Map<string, Card[]>();
  for (const card of cards) {
    const list = map.get(card.rarity) ?? [];
    list.push(card);
    map.set(card.rarity, list);
  }
  return map;
}

function poolFor(outcome: Outcome, pools: Map<string, Card[]>): Card[] {
  return outcome.rarities.flatMap((r) => pools.get(r) ?? []);
}

/**
 * Otevře jeden balíček: v každém slotu nejdřív losuje vzácné výsledky podle
 * jejich šance, jinak padne výchozí rarita. Stejná karta ve stejném provedení
 * se v jednom balíčku neopakuje (pokud to velikost sady dovolí).
 */
export function openPack(profile: PackProfile, pools: Map<string, Card[]>, rng: Rng = Math.random): PulledCard[] {
  const pulled: PulledCard[] = [];
  const seen = new Set<string>();

  for (const slot of profile.slots) {
    for (let i = 0; i < slot.count; i++) {
      let outcome = slot.base;
      let roll = rng();
      for (const hit of slot.hits) {
        const p = hit.p ?? 0;
        if (roll < p && poolFor(hit, pools).length > 0) {
          outcome = hit;
          break;
        }
        roll -= p;
      }

      const pool = poolFor(outcome, pools);
      if (pool.length === 0) continue;
      let card = pool[Math.floor(rng() * pool.length)];
      for (let tries = 0; seen.has(`${card.id}|${outcome.variant}`) && tries < 20; tries++) {
        card = pool[Math.floor(rng() * pool.length)];
      }
      seen.add(`${card.id}|${outcome.variant}`);
      pulled.push({ card, variant: outcome.variant });
    }
  }
  return pulled;
}
