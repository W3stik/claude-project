export interface SetInfo {
  id: string;
  name: string;
  series: string;
  code: string | null;
  releaseDate: string;
  printedTotal: number;
  total: number;
  logo: string;
  symbol: string;
}

export interface Card {
  id: string;
  name: string;
  number: number;
  rarity: string;
  supertype: string;
  subtypes: string[];
  types: string[];
  hp: string | null;
  artist: string | null;
  img: string;
  imgLarge: string;
  /** Prefix čísla u podsad (např. „CC“ u Classic Collection). */
  prefix?: string;
  /** Původní rarita reprintu z podsady. */
  printedRarity?: string | null;
}

/** Provedení karty: obyčejná, reverse holo a vzorované reverse holo z Black Bolt / White Flare. */
export type Variant = "normal" | "reverse" | "pokeball" | "masterball";

export interface PulledCard {
  card: Card;
  variant: Variant;
}
