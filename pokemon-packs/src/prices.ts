// Reálné tržní ceny karet. Hlavní zdroj je Pokémon TCG API (api.pokemontcg.io),
// které vrací ceny z TCGplayer (USD) i Cardmarket (EUR) pro celou sadu najednou.
// Když pro kartu nic nevrátí, zkusí se TCGdex (api.tcgdex.net) jen pro tu kartu.
// Ceny se ukládají do prohlížeče a obnovují se po 12 hodinách.
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
    const res = await fetch(url);
    if (!res.ok) throw new Error(`Ceny: HTTP ${res.status}`);
    const body = (await res.json()) as { data: ApiCard[]; totalCount: number };
    for (const card of body.data) out[card.id] = fromApiCard(card);
    if (page * 250 >= body.totalCount) break;
  }
  return out;
}

/**
 * Ceny všech karet sady (včetně podsad, např. me55 + me55c).
 * Při chybě sítě vrací poslední uložené ceny, případně prázdnou mapu.
 */
export async function loadSetPrices(setIds: string[]): Promise<PriceMap> {
  const parts = await Promise.all(setIds.map(loadOne));
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

export function hasPrices(setId: string): boolean {
  return memory.has(setId);
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

interface TcgdexPricing {
  cardmarket?: Record<string, unknown>;
  tcgplayer?: Record<string, Record<string, unknown> | unknown>;
}

function fromTcgdex(pricing: TcgdexPricing): CardPrice {
  const cm = pricing.cardmarket ?? {};
  const tp = (pricing.tcgplayer ?? {}) as Record<string, Record<string, unknown>>;
  const market = (k: string) => num(tp[k]?.marketPrice) ?? num(tp[k]?.midPrice);
  return {
    eur: num(cm.trend) ?? num(cm.avg) ?? num(cm["trend-holo"]) ?? num(cm["avg-holo"]),
    eurReverse: num(cm["trend-holo"]) ?? num(cm["avg-holo"]),
    usd: market("holofoil") ?? market("normal"),
    usdReverse: market("reverse-holofoil") ?? market("reverseHolofoil"),
    source: "tcgdex",
    updated: typeof cm.updated === "string" ? cm.updated : undefined,
  };
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

    const full = await getJson<{ pricing?: TcgdexPricing }>(`${TCGDEX}/cards/${match.id}`);
    return full.pricing ? fromTcgdex(full.pricing) : undefined;
  } catch {
    tcgdexSets = null;
    return undefined;
  }
}

const eurFmt = new Intl.NumberFormat("cs-CZ", { style: "currency", currency: "EUR" });
const usdFmt = new Intl.NumberFormat("cs-CZ", { style: "currency", currency: "USD" });

export const formatEur = (v: number | undefined) => (v === undefined ? "–" : eurFmt.format(v));
export const formatUsd = (v: number | undefined) => (v === undefined ? "–" : usdFmt.format(v));

/** Hodnota pro řazení: přednostně EUR (Cardmarket), jinak USD. */
export const sortValue = (p: { eur?: number; usd?: number }) => p.eur ?? p.usd ?? -1;
