import { type Outcome, type PackProfile, rarityInfo } from "./odds";
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
        if (roll < p) {
          // Když sada takovou kartu nemá, padne výchozí rarita (ne další vzácný výsledek).
          if (poolFor(hit, pools).length > 0) outcome = hit;
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

/** Uložitelná podoba balíčku (jen id karet a provedení). */
export const toSealed = (cards: PulledCard[]) => ({ cards: cards.map((c) => ({ id: c.card.id, variant: c.variant })) });

/** Obnoví karty uloženého balíčku; když některá karta v datech chybí, vrátí null. */
export function fromSealed(sealed: { cards: { id: string; variant: PulledCard["variant"] }[] }, byId: Map<string, Card>) {
  const cards: PulledCard[] = [];
  for (const ref of sealed.cards) {
    const card = byId.get(ref.id);
    if (!card) return null;
    cards.push({ card, variant: ref.variant });
  }
  return cards;
}

/**
 * Síla tajného náznaku na obalu: 0 = nic, 1 = Illustration / Ultra Rare,
 * 2 = Special Illustration Rare, 3 = zlatá a další nejvzácnější karty.
 */
export function hintLevel(cards: PulledCard[]): number {
  const best = Math.max(...cards.map((c) => rarityInfo(c.card.rarity).rank));
  return best >= 9 ? 3 : best >= 8 ? 2 : best >= 6 ? 1 : 0;
}
