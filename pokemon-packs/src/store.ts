// Stav hry uložený v prohlížeči (localStorage): neotevřené balíčky a sbírka.
import type { PulledCard, Variant } from "./types";

/** Balíček s předem určeným obsahem (z regálu v obchodě). */
export interface SealedPack {
  cards: { id: string; variant: Variant }[];
}

export interface PullRecord {
  setId: string;
  at: number;
  cards: { id: string; variant: Variant }[];
}

export interface GameState {
  version: 1;
  /** Neotevřené balíčky podle sady. */
  packs: Record<string, number>;
  /** Počet kusů: klíč „id karty|provedení“. */
  collection: Record<string, number>;
  /** Kdy byla karta získána poprvé (podle id karty). */
  firstSeen: Record<string, number>;
  /** Počet otevřených balíčků podle sady. */
  opened: Record<string, number>;
  /** Posledních několik otevřených balíčků. */
  history: PullRecord[];
  /** Regál v obchodě: 10 nabízených balíčků každé sady. */
  shelf: Record<string, SealedPack[]>;
  /** Vybrané balíčky z regálu čekající na otevření (jsou součástí počtu v `packs`). */
  sealed: Record<string, SealedPack[]>;
}

const KEY = "pokemon-packs:state:v1";
const HISTORY_LIMIT = 30;
const VARIANTS: Variant[] = ["normal", "reverse", "pokeball", "masterball"];

const empty = (): GameState => ({
  version: 1,
  packs: {},
  collection: {},
  firstSeen: {},
  opened: {},
  history: [],
  shelf: {},
  sealed: {},
});

// --- Kontrola stavu ----------------------------------------------------------
// Stav z localStorage i ze zálohy může být poškozený nebo ručně upravený,
// proto se z něj převezme jen to, co má správný tvar.

type Json = Record<string, unknown>;
type CardRef = { id: string; variant: Variant };

const isObject = (v: unknown): v is Json => typeof v === "object" && v !== null && !Array.isArray(v);
const isCount = (v: unknown): v is number => typeof v === "number" && Number.isInteger(v) && v > 0;
const isTime = (v: unknown): v is number => typeof v === "number" && Number.isFinite(v) && v > 0;
const isVariant = (v: unknown): v is Variant => VARIANTS.includes(v as Variant);
const isCollectionKey = (k: string) => k.indexOf("|") > 0 && isVariant(k.slice(k.lastIndexOf("|") + 1));

function numbers(v: unknown, valid: (n: unknown) => n is number, validKey: (k: string) => boolean = () => true) {
  const out: Record<string, number> = {};
  if (isObject(v)) for (const [k, n] of Object.entries(v)) if (validKey(k) && valid(n)) out[k] = n;
  return out;
}

/** Seznam karet balíčku; když je některá položka neplatná, je neplatný celý balíček. */
function cardRefs(v: unknown): CardRef[] | null {
  if (!Array.isArray(v) || v.length === 0) return null;
  const refs: CardRef[] = [];
  for (const c of v) {
    if (!isObject(c) || typeof c.id !== "string" || !isVariant(c.variant)) return null;
    refs.push({ id: c.id, variant: c.variant });
  }
  return refs;
}

function packLists(v: unknown): Record<string, SealedPack[]> {
  const out: Record<string, SealedPack[]> = {};
  if (!isObject(v)) return out;
  for (const [setId, list] of Object.entries(v)) {
    if (!Array.isArray(list)) continue;
    const packs = list.flatMap((p) => {
      const cards = isObject(p) ? cardRefs(p.cards) : null;
      return cards ? [{ cards }] : [];
    });
    if (packs.length) out[setId] = packs;
  }
  return out;
}

/** Převede neznámá data na platný stav hry; když to vůbec není stav hry, vyhodí chybu. */
export function sanitize(raw: unknown): GameState {
  if (!isObject(raw) || raw.version !== 1 || !isObject(raw.collection)) {
    throw new Error("Soubor neobsahuje zálohu sbírky");
  }
  const packs = numbers(raw.packs, isCount);
  const sealed = packLists(raw.sealed);
  // Vybraných balíčků nesmí být víc, než kolik jich hráč má.
  for (const [setId, list] of Object.entries(sealed)) {
    list.length = Math.min(list.length, packs[setId] ?? 0);
    if (list.length === 0) delete sealed[setId];
  }
  const history = Array.isArray(raw.history)
    ? raw.history.flatMap((r): PullRecord[] => {
        if (!isObject(r) || typeof r.setId !== "string" || !isTime(r.at)) return [];
        const cards = cardRefs(r.cards);
        return cards ? [{ setId: r.setId, at: r.at, cards }] : [];
      })
    : [];
  return {
    version: 1,
    packs,
    collection: numbers(raw.collection, isCount, isCollectionKey),
    firstSeen: numbers(raw.firstSeen, isTime),
    opened: numbers(raw.opened, isCount),
    history: history.slice(0, HISTORY_LIMIT),
    shelf: packLists(raw.shelf),
    sealed,
  };
}

// --- Uložení a souběh více oken ---------------------------------------------

/** Když se uložení nepovede (plné úložiště), platí dál stav v paměti a z úložiště se nečte. */
let storageBroken = false;

function readStored(): GameState | null {
  try {
    const raw = localStorage.getItem(KEY);
    return raw === null ? null : sanitize(JSON.parse(raw));
  } catch {
    return null;
  }
}

let state = readStored() ?? empty();
const listeners = new Set<() => void>();
const notify = () => listeners.forEach((fn) => fn());

function save() {
  try {
    localStorage.setItem(KEY, JSON.stringify(state));
    storageBroken = false;
  } catch {
    // Plné nebo zakázané úložiště: hra běží dál, jen se stav neuloží.
    storageBroken = true;
  }
  notify();
}

/**
 * Každá změna nejdřív načte aktuální uložený stav, takže aplikace otevřená
 * ve dvou oknech (např. nainstalovaná a v prohlížeči) si nepřepíše karty.
 */
function mutate<T>(fn: (s: GameState) => T): T {
  if (!storageBroken) state = readStored() ?? state;
  const result = fn(state);
  save();
  return result;
}

// Změna z jiného okna se hned převezme.
if (typeof window !== "undefined") {
  window.addEventListener("storage", (e) => {
    if (e.key !== KEY && e.key !== null) return;
    state = readStored() ?? empty();
    notify();
  });
}

export const getState = (): GameState => state;

export function subscribe(fn: () => void): () => void {
  listeners.add(fn);
  return () => listeners.delete(fn);
}

export const collectionKey = (cardId: string, variant: Variant) => `${cardId}|${variant}`;

export function addPacks(setId: string, count: number) {
  mutate((s) => {
    s.packs[setId] = (s.packs[setId] ?? 0) + count;
  });
}

export function setShelf(setId: string, packs: SealedPack[]) {
  mutate((s) => {
    s.shelf[setId] = [...packs];
  });
}

/** Vezme balíček z regálu do zásoby a na jeho místo dá nový. */
export function pickFromShelf(setId: string, index: number, replacement: SealedPack) {
  mutate((s) => {
    const shelf = s.shelf[setId];
    if (!shelf?.[index]) throw new Error("Balíček na regálu není");
    (s.sealed[setId] ??= []).push(shelf[index]);
    shelf[index] = replacement;
    s.packs[setId] = (s.packs[setId] ?? 0) + 1;
  });
}

/** Další vybraný balíček sady, který se otevře jako první (bez odebrání). */
export const nextSealed = (setId: string): SealedPack | undefined => state.sealed[setId]?.[0];

export const unopenedTotal = () => Object.values(state.packs).reduce((a, b) => a + b, 0);

/** Odebere balíček ze zásoby a přidá jeho karty do sbírky. Vrací id karet, které jsou nové. */
export function recordOpening(setId: string, cards: PulledCard[]): Set<string> {
  return mutate((s) => {
    if (!s.packs[setId]) throw new Error("Žádný neotevřený balíček této sady");
    s.packs[setId] -= 1;
    if (s.packs[setId] === 0) delete s.packs[setId];
    s.sealed[setId]?.shift();
    if (s.sealed[setId]?.length === 0) delete s.sealed[setId];

    const fresh = new Set<string>();
    const now = Date.now();
    for (const { card, variant } of cards) {
      const key = collectionKey(card.id, variant);
      if (!s.collection[key]) fresh.add(key);
      s.collection[key] = (s.collection[key] ?? 0) + 1;
      s.firstSeen[card.id] ??= now;
    }
    s.opened[setId] = (s.opened[setId] ?? 0) + 1;
    s.history.unshift({ setId, at: now, cards: cards.map((c) => ({ id: c.card.id, variant: c.variant })) });
    s.history.length = Math.min(s.history.length, HISTORY_LIMIT);
    return fresh;
  });
}

/** Počty kusů karty podle provedení. */
export function countsFor(cardId: string): Partial<Record<Variant, number>> {
  const out: Partial<Record<Variant, number>> = {};
  for (const variant of VARIANTS) {
    const n = state.collection[collectionKey(cardId, variant)];
    if (n) out[variant] = n;
  }
  return out;
}

export const totalCount = (cardId: string) =>
  Object.values(countsFor(cardId)).reduce((a, b) => a + (b ?? 0), 0);

/** Souhrn stavu pro potvrzovací dotazy: kusy karet a neotevřené balíčky. */
export function stateSummary(s: GameState = state) {
  const sum = (r: Record<string, number>) => Object.values(r).reduce((a, b) => a + b, 0);
  return { cards: sum(s.collection), packs: sum(s.packs) };
}

export function exportState(): string {
  return JSON.stringify(state, null, 1);
}

/** Přečte a zkontroluje zálohu (zatím ji nepoužije). */
export function parseBackup(json: string): GameState {
  let raw: unknown;
  try {
    raw = JSON.parse(json);
  } catch {
    throw new Error("Soubor není platná záloha (chybný JSON)");
  }
  return sanitize(raw);
}

/** Nahradí celý stav zálohou. */
export function importState(backup: string | GameState) {
  const next = typeof backup === "string" ? parseBackup(backup) : sanitize(backup);
  mutate((s) => Object.assign(s, next));
}

export function resetState() {
  mutate((s) => Object.assign(s, empty()));
}
