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

function load(): GameState {
  try {
    const raw = localStorage.getItem(KEY);
    if (!raw) return empty();
    const parsed = JSON.parse(raw) as GameState;
    return parsed.version === 1 ? { ...empty(), ...parsed } : empty();
  } catch {
    return empty();
  }
}

let state = load();
const listeners = new Set<() => void>();

function save() {
  try {
    localStorage.setItem(KEY, JSON.stringify(state));
  } catch {
    // Plné nebo zakázané úložiště: hra běží dál, jen se stav neuloží.
  }
  listeners.forEach((fn) => fn());
}

export const getState = (): GameState => state;

export function subscribe(fn: () => void): () => void {
  listeners.add(fn);
  return () => listeners.delete(fn);
}

export const collectionKey = (cardId: string, variant: Variant) => `${cardId}|${variant}`;

export function addPacks(setId: string, count: number) {
  state.packs[setId] = (state.packs[setId] ?? 0) + count;
  save();
}

export function setShelf(setId: string, packs: SealedPack[]) {
  state.shelf[setId] = [...packs];
  save();
}

/** Vezme balíček z regálu do zásoby a na jeho místo dá nový. */
export function pickFromShelf(setId: string, index: number, replacement: SealedPack) {
  const shelf = state.shelf[setId];
  if (!shelf?.[index]) throw new Error("Balíček na regálu není");
  (state.sealed[setId] ??= []).push(shelf[index]);
  shelf[index] = replacement;
  state.packs[setId] = (state.packs[setId] ?? 0) + 1;
  save();
}

/** Další vybraný balíček sady, který se otevře jako první (bez odebrání). */
export const nextSealed = (setId: string): SealedPack | undefined => state.sealed[setId]?.[0];

export const unopenedTotal = () => Object.values(state.packs).reduce((a, b) => a + b, 0);

/** Odebere balíček ze zásoby a přidá jeho karty do sbírky. Vrací id karet, které jsou nové. */
export function recordOpening(setId: string, cards: PulledCard[]): Set<string> {
  if (!state.packs[setId]) throw new Error("Žádný neotevřený balíček této sady");
  state.packs[setId] -= 1;
  if (state.packs[setId] === 0) delete state.packs[setId];
  state.sealed[setId]?.shift();
  if (state.sealed[setId]?.length === 0) delete state.sealed[setId];

  const fresh = new Set<string>();
  const now = Date.now();
  for (const { card, variant } of cards) {
    const key = collectionKey(card.id, variant);
    if (!state.collection[key]) fresh.add(key);
    state.collection[key] = (state.collection[key] ?? 0) + 1;
    state.firstSeen[card.id] ??= now;
  }
  state.opened[setId] = (state.opened[setId] ?? 0) + 1;
  state.history.unshift({ setId, at: now, cards: cards.map((c) => ({ id: c.card.id, variant: c.variant })) });
  state.history.length = Math.min(state.history.length, HISTORY_LIMIT);
  save();
  return fresh;
}

/** Počty kusů karty podle provedení. */
export function countsFor(cardId: string): Partial<Record<Variant, number>> {
  const out: Partial<Record<Variant, number>> = {};
  for (const variant of ["normal", "reverse", "pokeball", "masterball"] as Variant[]) {
    const n = state.collection[collectionKey(cardId, variant)];
    if (n) out[variant] = n;
  }
  return out;
}

export const totalCount = (cardId: string) =>
  Object.values(countsFor(cardId)).reduce((a, b) => a + (b ?? 0), 0);

export function exportState(): string {
  return JSON.stringify(state, null, 1);
}

export function importState(json: string) {
  const parsed = JSON.parse(json) as GameState;
  if (parsed.version !== 1 || typeof parsed.collection !== "object") {
    throw new Error("Soubor neobsahuje zálohu sbírky");
  }
  state = { ...empty(), ...parsed };
  save();
}

export function resetState() {
  state = empty();
  save();
}
