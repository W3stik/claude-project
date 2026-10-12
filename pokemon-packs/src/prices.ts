// Reálné tržní ceny karet (Cardmarket v EUR, TCGplayer v USD).
//  1. data/prices.json: ceny z TCGdex stažené při buildu (scripts/fetch-prices.mjs),
//     takže jsou k dispozici hned a i offline.
//  2. Pokémon TCG API (api.pokemontcg.io) pro sady, které v souboru chybí.
//  3. TCGdex (api.tcgdex.net) živě pro jednu kartu v jejím detailu.
// Živé ceny se ukládají do prohlížeče a obnovují se po 12 hodinách.
import { parseTcgdexPricing } from "./tcgdexPricing.js";
import type { Card, Variant } from "./types";

export interface CardPrice {
  /** Cardmarket trend v EUR. */
  eur?: number;
  eurReverse?: number;
  /** TCGplayer market price v USD. */
  usd?: number;
  usdReverse?: number;
  cardmarketUrl?: string;
  tcgplayerUrl?: string;
  source: "pokemontcg.io" | "tcgdex";
  updated?: string;
}

type PriceMap = Record<string, CardPrice>;

const TTL = 12 * 60 * 60 * 1000;
const API = "https://api.pokemontcg.io/v2/cards";
const TCGDEX = "https://api.tcgdex.net/v2/en";
const storageKey = (setId: string) => `pokemon-packs:prices:${setId}`;

const memory = new Map<string, PriceMap>();
const inflight = new Map<string, Promise<PriceMap>>();

const num = (v: unknown): number | undefined => (typeof v === "number" && v > 0 ? v : undefined);

function readCache(setId: string): { at: number; data: PriceMap } | null {
  try {
    const raw = localStorage.getItem(storageKey(setId));
    return raw ? JSON.parse(raw) : null;
  } catch {
    return null;
  }
}

function writeCache(setId: string, data: PriceMap) {
  try {
    localStorage.setItem(storageKey(setId), JSON.stringify({ at: Date.now(), data }));
  } catch {
    // Úložiště je plné: ceny zůstanou jen v paměti.
  }
}

interface ApiCard {
  id: string;
  tcgplayer?: { url?: string; updatedAt?: string; prices?: Record<string, { market?: number; mid?: number }> };
  cardmarket?: {
    url?: string;
    updatedAt?: string;
    prices?: { trendPrice?: number; averageSellPrice?: number; avg7?: number; reverseHoloTrend?: number; reverseHoloSell?: number };
  };
}

function fromApiCard(c: ApiCard): CardPrice {
  const tp = c.tcgplayer?.prices ?? {};
  const main = tp.holofoil ?? tp.normal ?? Object.values(tp).find((p) => p !== tp.reverseHolofoil);
  const cm = c.cardmarket?.prices ?? {};
  return {
    eur: num(cm.trendPrice) ?? num(cm.averageSellPrice) ?? num(cm.avg7),
    eurReverse: num(cm.reverseHoloTrend) ?? num(cm.reverseHoloSell),
    usd: num(main?.market) ?? num(main?.mid),
    usdReverse: num(tp.reverseHolofoil?.market) ?? num(tp.reverseHolofoil?.mid),
    cardmarketUrl: c.cardmarket?.url,
    tcgplayerUrl: c.tcgplayer?.url,
    source: "pokemontcg.io",
    updated: c.cardmarket?.updatedAt ?? c.tcgplayer?.updatedAt,
  };
}

async function fetchSet(setId: string): Promise<PriceMap> {
  const out: PriceMap = {};
  for (let page = 1; page < 10; page++) {
    const url = `${API}?q=set.id:${setId}&select=id,tcgplayer,cardmarket&pageSize=250&page=${page}`;
    // API občas vrátí chybu 500, proto to zkusíme víckrát.
    let res = await fetch(url);
    for (let attempt = 1; !res.ok && res.status >= 500 && attempt < 3; attempt++) {
      await new Promise((r) => setTimeout(r, 800 * attempt));
      res = await fetch(url);
    }
    if (!res.ok) throw new Error(`Ceny: HTTP ${res.status}`);
    const body = (await res.json()) as { data: ApiCard[]; totalCount: number };
    for (const card of body.data) out[card.id] = fromApiCard(card);
    if (page * 250 >= body.totalCount) break;
  }
  return out;
}

interface BundledFile {
  updated: string;
  cards: Record<string, Omit<CardPrice, "source">>;
}

let bundled: Promise<Map<string, PriceMap>> | null = null;

/** Ceny přibalené k aplikaci, rozdělené podle sady. */
function loadBundled(): Promise<Map<string, PriceMap>> {
  bundled ??= fetch(`${import.meta.env.BASE_URL}data/prices.json`)
    .then((res) => (res.ok ? (res.json() as Promise<BundledFile>) : null))
    .then((file) => {
      const bySet = new Map<string, PriceMap>();
      if (!file) return bySet;
      for (const [id, price] of Object.entries(file.cards)) {
        const setId = id.slice(0, id.lastIndexOf("-"));
        const map = bySet.get(setId) ?? {};
        map[id] = { ...price, source: "tcgdex", updated: file.updated.slice(0, 10) };
        bySet.set(setId, map);
      }
      return bySet;
    })
    .catch(() => new Map());
  return bundled;
}

/**
 * Ceny všech karet sady (včetně podsad, např. me55 + me55c).
 * Při chybě sítě vrací poslední uložené ceny, případně prázdnou mapu.
 */
export async function loadSetPrices(setIds: string[]): Promise<PriceMap> {
  const local = await loadBundled();
  const parts = await Promise.all(setIds.map((id) => local.get(id) ?? loadOne(id)));
  return Object.assign({}, ...parts);
}

function loadOne(setId: string): Promise<PriceMap> {
  const mem = memory.get(setId);
  if (mem) return Promise.resolve(mem);
  const cached = readCache(setId);
  if (cached && Date.now() - cached.at < TTL) {
    memory.set(setId, cached.data);
    return Promise.resolve(cached.data);
  }
  let p = inflight.get(setId);
  if (!p) {
    p = fetchSet(setId)
      .then((data) => {
        memory.set(setId, data);
        writeCache(setId, data);
        return data;
      })
      .catch(() => cached?.data ?? {})
      .finally(() => inflight.delete(setId));
    inflight.set(setId, p);
  }
  return p;
}

/** Cena konkrétního provedení karty. Reverse a vzorované holo mají vlastní cenu, pokud ji trh uvádí. */
export function variantPrice(price: CardPrice | undefined, variant: Variant): { eur?: number; usd?: number } {
  if (!price) return {};
  if (variant === "normal") return { eur: price.eur, usd: price.usd };
  return { eur: price.eurReverse ?? price.eur, usd: price.usdReverse ?? price.usd };
}

// --- Záloha: TCGdex, jen pro jednotlivou kartu -----------------------------

let tcgdexSets: Promise<{ id: string; name: string }[]> | null = null;
const tcgdexSetCards = new Map<string, Promise<{ id: string; localId: string; name: string }[]>>();

async function getJson<T>(url: string): Promise<T> {
  const res = await fetch(url);
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  return res.json() as Promise<T>;
}

/** Dohledá cenu jedné karty v TCGdex podle názvu sady a čísla (nebo jména u podsad). */
export async function tcgdexPrice(card: Card, setName: string): Promise<CardPrice | undefined> {
  try {
    tcgdexSets ??= getJson(`${TCGDEX}/sets`);
    const sets = await tcgdexSets;
    const want = setName.toLowerCase();
    const set = sets.find((s) => s.name.toLowerCase() === want);
    if (!set) return undefined;

    let cards = tcgdexSetCards.get(set.id);
    if (!cards) {
      cards = getJson<{ cards: { id: string; localId: string; name: string }[] }>(`${TCGDEX}/sets/${set.id}`).then(
        (s) => s.cards,
      );
      tcgdexSetCards.set(set.id, cards);
    }
    const match = card.prefix
      ? (await cards).find((c) => c.name === card.name)
      : (await cards).find((c) => Number(c.localId) === card.number);
    if (!match) return undefined;

    const full = await getJson<{ pricing?: { cardmarket?: { updated?: unknown } } }>(`${TCGDEX}/cards/${match.id}`);
    if (!full.pricing) return undefined;
    const updated = full.pricing.cardmarket?.updated;
    return { ...parseTcgdexPricing(full.pricing), source: "tcgdex", updated: typeof updated === "string" ? updated : undefined };
  } catch {
    tcgdexSets = null;
    return undefined;
  }
}

const eurFmt = new Intl.NumberFormat("cs-CZ", { style: "currency", currency: "EUR" });
const usdFmt = new Intl.NumberFormat("cs-CZ", { style: "currency", currency: "USD" });

export const formatEur = (v: number | undefined) => (v === undefined ? "–" : eurFmt.format(v));
export const formatUsd = (v: number | undefined) => (v === undefined ? "–" : usdFmt.format(v));

/** Součet cen. Měna, ve které žádná karta cenu nemá, zůstane prázdná (nezobrazí se jako 0). */
export interface PriceTotal {
  eur?: number;
  usd?: number;
}

export function addPrice(total: PriceTotal, price: { eur?: number; usd?: number }, count = 1) {
  if (price.eur !== undefined) total.eur = (total.eur ?? 0) + price.eur * count;
  if (price.usd !== undefined) total.usd = (total.usd ?? 0) + price.usd * count;
}

export function formatTotal(total: PriceTotal, withSource = false): string {
  const parts: string[] = [];
  if (total.eur !== undefined) parts.push(`${formatEur(total.eur)}${withSource ? " (Cardmarket)" : ""}`);
  if (total.usd !== undefined) parts.push(`${formatUsd(total.usd)}${withSource ? " (TCGplayer)" : ""}`);
  return parts.length ? parts.join(" · ") : "ceny nejsou dostupné";
}

/** Hodnota pro řazení: přednostně EUR (Cardmarket), jinak USD. */
export const sortValue = (p: { eur?: number; usd?: number }) => p.eur ?? p.usd ?? -1;
