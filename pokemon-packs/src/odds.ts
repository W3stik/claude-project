// Složení balíčků a šance na tah jednotlivých rarit.
//
// The Pokémon Company šance oficiálně nezveřejňuje. Čísla níže pocházejí
// z měření TCGplayer Authentication Center (tisíce otevřených balíčků) a tam,
// kde chybí, z komunitních sčítání. Každá sada má u sebe uvedené zdroje.
import type { Variant } from "./types";

export interface RarityInfo {
  /** Pořadí od nejběžnější po nejvzácnější. */
  rank: number;
  /** Zkratka zobrazovaná na kartě v albu. */
  short: string;
  /** Barva rarity v rozhraní. */
  color: string;
  /** Typ lesku při zobrazení karty. */
  shine: "none" | "holo" | "rainbow" | "gold" | "dark";
  /** Zda jde o „hit“, který si zaslouží zvláštní animaci při odhalení. */
  hit: boolean;
}

export const RARITIES: Record<string, RarityInfo> = {
  Common: { rank: 0, short: "C", color: "#9aa3ad", shine: "none", hit: false },
  Uncommon: { rank: 1, short: "U", color: "#5fb3a1", shine: "none", hit: false },
  Rare: { rank: 2, short: "R", color: "#e6c84f", shine: "holo", hit: false },
  "Pikachu Rare": { rank: 3, short: "PR", color: "#ffd84a", shine: "holo", hit: false },
  "Double Rare": { rank: 4, short: "RR", color: "#f0a33a", shine: "holo", hit: true },
  "Classic Collection": { rank: 5, short: "CC", color: "#c48af0", shine: "holo", hit: true },
  "Illustration Rare": { rank: 6, short: "IR", color: "#55c1f2", shine: "rainbow", hit: true },
  "Ultra Rare": { rank: 7, short: "UR", color: "#c9d4e0", shine: "rainbow", hit: true },
  "Mega Attack Rare": { rank: 7, short: "MAR", color: "#ff6fa8", shine: "rainbow", hit: true },
  "Special Illustration Rare": { rank: 8, short: "SIR", color: "#ff7ad9", shine: "rainbow", hit: true },
  "Hyper Rare": { rank: 9, short: "HR", color: "#ffcf3f", shine: "gold", hit: true },
  "Mega Hyper Rare": { rank: 9, short: "MHR", color: "#ffcf3f", shine: "gold", hit: true },
  "Futuristic Rare": { rank: 9, short: "FR", color: "#7df9ff", shine: "rainbow", hit: true },
  "Black White Rare": { rank: 10, short: "BWR", color: "#f4f4f4", shine: "dark", hit: true },
};

export const rarityInfo = (rarity: string): RarityInfo =>
  RARITIES[rarity] ?? { rank: 2, short: "?", color: "#888", shine: "holo", hit: false };

export const VARIANT_LABEL: Record<Variant, string> = {
  normal: "Normální",
  reverse: "Reverse holo",
  pokeball: "Poké Ball holo",
  masterball: "Master Ball holo",
};

/** Výsledek, který může padnout ve slotu: rarita (nebo skupina rarit) a provedení. */
export interface Outcome {
  rarities: string[];
  variant: Variant;
  /** Pravděpodobnost na balíček (0–1). U výchozího výsledku se neuvádí. */
  p?: number;
}

export interface Slot {
  label: string;
  /** Kolik karet z tohoto slotu v balíčku je. */
  count: number;
  /** Vzácné výsledky, losují se postupně podle pravděpodobnosti. */
  hits: Outcome[];
  /** Co padne, když nepadne žádný vzácný výsledek. */
  base: Outcome;
}

export interface Source {
  label: string;
  url: string;
}

export interface PackProfile {
  /** Barvy obalu balíčku. */
  colors: [string, string];
  slots: Slot[];
  note?: string;
  sources: Source[];
}

const REVERSE_POOL = ["Common", "Uncommon", "Rare"];

const commons = (count: number): Slot => ({
  label: "Common",
  count,
  hits: [],
  base: { rarities: ["Common"], variant: "normal" },
});

const uncommons = (count: number): Slot => ({
  label: "Uncommon",
  count,
  hits: [],
  base: { rarities: ["Uncommon"], variant: "normal" },
});

const reverse = (label = "Reverse holo"): Slot => ({
  label,
  count: 1,
  hits: [],
  base: { rarities: REVERSE_POOL, variant: "reverse" },
});

interface StandardRates {
  doubleRare: number;
  ultraRare: number;
  illustrationRare: number;
  specialIllustrationRare: number;
  /** Zlatá karta: Hyper Rare (Scarlet & Violet) nebo Mega Hyper Rare (Mega Evolution). */
  gold: number;
  goldRarity: "Hyper Rare" | "Mega Hyper Rare";
  megaAttackRare?: number;
}

/**
 * Standardní balíček éry Scarlet & Violet a Mega Evolution:
 * 4 Common, 3 Uncommon, 2 reverse holo (druhý z nich může být IR/SIR/zlatá)
 * a 1 Rare slot (Rare, Double Rare, Ultra Rare…). Plus Basic Energy a kód,
 * které se nesbírají.
 */
const standardSlots = (r: StandardRates): Slot[] => [
  commons(4),
  uncommons(3),
  reverse(),
  {
    label: "Reverse holo / Illustration",
    count: 1,
    hits: [
      { rarities: [r.goldRarity], variant: "normal", p: r.gold },
      { rarities: ["Special Illustration Rare"], variant: "normal", p: r.specialIllustrationRare },
      { rarities: ["Illustration Rare"], variant: "normal", p: r.illustrationRare },
    ],
    base: { rarities: REVERSE_POOL, variant: "reverse" },
  },
  {
    label: "Rare",
    count: 1,
    hits: [
      ...(r.megaAttackRare
        ? [{ rarities: ["Mega Attack Rare"], variant: "normal" as const, p: r.megaAttackRare }]
        : []),
      { rarities: ["Ultra Rare"], variant: "normal", p: r.ultraRare },
      { rarities: ["Double Rare"], variant: "normal", p: r.doubleRare },
    ],
    base: { rarities: ["Rare"], variant: "normal" },
  },
];

const TCGPLAYER = "https://www.tcgplayer.com/content/article/";

/** Mega Evolution sady s „klasickými“ šancemi naměřenými TCGplayer (ME1, PFL, POR, CRI, PBL). */
const megaEvolutionRates = (overrides: Partial<StandardRates> = {}): StandardRates => ({
  doubleRare: 0.2077,
  ultraRare: 0.0806,
  illustrationRare: 0.1097,
  specialIllustrationRare: 0.0125,
  gold: 0.0008,
  goldRarity: "Mega Hyper Rare",
  ...overrides,
});

const blackWhite = (colors: [string, string]): PackProfile => ({
  colors,
  slots: [
    commons(4),
    uncommons(3),
    {
      label: "Reverse / Poké Ball",
      count: 1,
      hits: [{ rarities: REVERSE_POOL, variant: "pokeball", p: 1 / 3 }],
      base: { rarities: REVERSE_POOL, variant: "reverse" },
    },
    {
      label: "Reverse / Master Ball / Illustration",
      count: 1,
      hits: [
        { rarities: ["Black White Rare"], variant: "normal", p: 1 / 1789 },
        { rarities: ["Special Illustration Rare"], variant: "normal", p: 1 / 80 },
        { rarities: ["Illustration Rare"], variant: "normal", p: 0.1639 },
        { rarities: REVERSE_POOL, variant: "masterball", p: 1 / 19 },
      ],
      base: { rarities: REVERSE_POOL, variant: "reverse" },
    },
    {
      label: "Rare",
      count: 1,
      hits: [
        { rarities: ["Ultra Rare"], variant: "normal", p: 1 / 17 },
        { rarities: ["Double Rare"], variant: "normal", p: 0.2111 },
      ],
      base: { rarities: ["Rare"], variant: "normal" },
    },
  ],
  note:
    "Black White Rare nebyla ve vzorku TCGplayer (700+ balíčků) ani jednou, šance 1:1789 je komunitní odhad. Poké Ball vzor ~1:3, Master Ball vzor ~1:19.",
  sources: [
    { label: "Deltia's Gaming – Black Bolt / White Flare Pull Rates (data TCGplayer)", url: "https://deltiasgaming.com/?p=299238" },
    { label: "CardCodex – Black Bolt / White Flare pull rates", url: "https://cardcodex.com/blog/black-bolt-white-flare-pull-rates/" },
    { label: "TCGTalk – Black Bolt value guide", url: "https://tcgtalk.com/guides/black-bolt-pack-opening-value-guide" },
  ],
});

export const PACKS: Record<string, PackProfile> = {
  sv10: {
    colors: ["#1b1b2f", "#b3122e"],
    slots: standardSlots({
      doubleRare: 0.2,
      ultraRare: 1 / 16,
      illustrationRare: 1 / 12,
      specialIllustrationRare: 1 / 94,
      gold: 1 / 149,
      goldRarity: "Hyper Rare",
    }),
    note: "Zdroje se u Destined Rivals rozcházejí (SIR 1:83–1:100). Použity hodnoty z 8 000+ balíčků TCGplayer, jak je cituje Deltia's Gaming.",
    sources: [
      { label: "Deltia's Gaming – Destined Rivals Pull Rates (data TCGplayer)", url: "https://deltiasgaming.com/?p=249103" },
      { label: "TCGTalk – Destined Rivals value guide", url: "https://tcgtalk.com/guides/destined-rivals-pack-opening-value-guide" },
      { label: "TCG Watchtower – Destined Rivals", url: "https://tcgwatchtower.com/pokemon/sets/scarlet-violet/destined-rivals/cards" },
    ],
  },
  zsv10pt5: blackWhite(["#0d0d0d", "#3a3f4a"]),
  rsv10pt5: blackWhite(["#f4f1ea", "#c9a86a"]),
  me1: {
    colors: ["#1f3c88", "#6fd3ff"],
    slots: standardSlots(
      megaEvolutionRates({ doubleRare: 0.2, ultraRare: 1 / 12, illustrationRare: 0.1089, specialIllustrationRare: 0.0099, gold: 1 / 1260 }),
    ),
    sources: [
      { label: "TCGplayer – Mega Evolution Pull Rates", url: `${TCGPLAYER}Pok%C3%A9mon-TCG-Mega-Evolution-Pull-Rates/40cbeedc-21ce-473b-aef1-74e3969d9f91/` },
      { label: "Screen Rant – Mega Hyper Rare odds", url: "https://screenrant.com/pokemon-mega-evolution-cards-pull-rates-rarest-ever/" },
    ],
  },
  me2: {
    colors: ["#2a0b0b", "#ff5a1f"],
    slots: standardSlots(megaEvolutionRates()),
    sources: [
      { label: "TCGplayer – Phantasmal Flames Pull Rates", url: `${TCGPLAYER}Pok%C3%A9mon-TCG-Phantasmal-Flames-Pull-Rates/9abae60d-b7fb-448f-874e-176f78d6a6ca/` },
    ],
  },
  me2pt5: {
    colors: ["#2b1650", "#f2c14e"],
    slots: standardSlots({
      doubleRare: 0.2,
      ultraRare: 1 / 21,
      megaAttackRare: 1 / 29,
      illustrationRare: 1 / 9,
      specialIllustrationRare: 1 / 70,
      gold: 1 / 540,
      goldRarity: "Mega Hyper Rare",
    }),
    note: "Mega Attack Rare zabírají místo Ultra Rare, proto jsou Ultra Rare vzácnější (1:21). God packy ve výpočtu nejsou.",
    sources: [
      { label: "TCGplayer – Ascended Heroes Pull Rates", url: `${TCGPLAYER}Pok%C3%A9mon-TCG-Ascended-Heroes-Pull-Rates/60143d94-88a7-42ce-8e73-babd7b3fabd6/` },
      { label: "PokeBeach – Ascended Heroes pull rates", url: "https://www.pokebeach.com/2026/02/ascended-heroes-pull-rates-finally-determined-better-than-usual" },
      { label: "CardCodex – Ascended Heroes pull rates", url: "https://cardcodex.com/blog/ascended-heroes-pull-rates-explained/" },
    ],
  },
  me3: {
    colors: ["#0f3b2e", "#7ee0b5"],
    slots: standardSlots(megaEvolutionRates({ ultraRare: 1 / 12, illustrationRare: 1 / 9, gold: 1 / 1786 })),
    note: "TCGplayer měl u Perfect Order menší vzorek; šance odpovídají předchozím sadám Mega Evolution.",
    sources: [
      { label: "TCGplayer – Perfect Order Pull Rates", url: `${TCGPLAYER}Pok%C3%A9mon-TCG-Perfect-Order-Pull-Rates/73148119-ebcb-40b7-84b6-52b3a6d0c631/` },
    ],
  },
  me4: {
    colors: ["#06263d", "#3fb6e8"],
    slots: standardSlots(megaEvolutionRates({ doubleRare: 0.2, illustrationRare: 0.11, specialIllustrationRare: 1 / 83, gold: 1 / 1000 })),
    note: "U Chaos Rising zatím není článek TCGplayer. Double Rare a IR podle vzorku 5 000+ balíčků (Cardlines), SIR a MHR jsou komunitní odhady.",
    sources: [
      { label: "Cardlines – Chaos Rising pull rates", url: "https://cardlines.com/chaos-rising-one-after-release-pull-rates-prices-and-what-to-buy/" },
      { label: "TCGTalk – Chaos Rising pull rates", url: "https://tcgtalk.com/guides/chaos-rising-pull-rates" },
      { label: "ComicBook – Chaos Rising estimates", url: "https://comicbook.com/gaming/feature/pokemon-tcg-chaos-rising-pull-rates-ex-illustration-rares-estimates/" },
    ],
  },
  me5: {
    colors: ["#09070f", "#6b3fa0"],
    slots: standardSlots(megaEvolutionRates({ doubleRare: 0.2102, ultraRare: 0.083, illustrationRare: 0.1101, gold: 0.0009 })),
    sources: [
      { label: "TCGplayer – Pitch Black Pull Rates", url: `${TCGPLAYER}Pok%C3%A9mon-TCG-Pitch-Black-Pull-Rates/069a5fda-2d1f-44a1-97de-b6dcdc5abfb8/` },
    ],
  },
  me55: {
    colors: ["#c8102e", "#ffd400"],
    slots: [
      {
        label: "Common (foil)",
        count: 2,
        hits: [],
        base: { rarities: ["Common"], variant: "normal" },
      },
      {
        label: "Rare",
        count: 1,
        hits: [
          { rarities: ["Classic Collection"], variant: "normal", p: 1 / 10.5 },
          { rarities: ["Double Rare"], variant: "normal", p: 1 / 4.4 },
        ],
        base: { rarities: ["Rare"], variant: "normal" },
      },
      {
        label: "Illustration",
        count: 1,
        hits: [
          { rarities: ["Futuristic Rare"], variant: "normal", p: 1 / 120 },
          { rarities: ["Special Illustration Rare"], variant: "normal", p: 1 / 19.8 },
          { rarities: ["Illustration Rare"], variant: "normal", p: 1 / 5.6 },
        ],
        base: { rarities: ["Common"], variant: "normal" },
      },
      {
        label: "Pikachu Rare",
        count: 1,
        hits: [],
        base: { rarities: ["Pikachu Rare"], variant: "normal" },
      },
    ],
    note: "Speciální sada: 5 foil karet, poslední je vždy jeden z 30 Pikachu Rare. Futuristic Rare podle 3 000 balíčků TCGplayer, ostatní rarity podle ~800 komunitně zapsaných balíčků.",
    sources: [
      { label: "TCGplayer – 30th Celebration Pull Rates", url: `${TCGPLAYER}Pok%C3%A9mon-TCG-30th-Celebration-Pull-Rates/587b3657-481a-4ab8-827c-68cd3ab585b0/` },
      { label: "cardprice.com – 30th Celebration measured odds", url: "https://cardprice.com/guides/30th-celebration-pull-rates" },
      { label: "Treasure Vault – 30th Celebration early data", url: "https://treasurevaultau.com/blogs/news/pokemon-tcg-30th-celebration-pull-rates" },
    ],
  },
};

/** Výchozí profil pro sadu, pro kterou zatím nemáme naměřené šance. */
export const DEFAULT_PACK: PackProfile = {
  colors: ["#23324a", "#8aa4c8"],
  slots: standardSlots(megaEvolutionRates()),
  note: "Pro tuto sadu zatím nejsou naměřené šance, používají se průměrné hodnoty éry Mega Evolution.",
  sources: [],
};

export const packProfile = (setId: string): PackProfile => PACKS[setId] ?? DEFAULT_PACK;

/** Celkový počet karet v balíčku. */
export const packSize = (profile: PackProfile): number =>
  profile.slots.reduce((n, s) => n + s.count, 0);

/**
 * Šance na balíček pro každou raritu, která může padnout ve vzácném slotu,
 * přepočtená na tvar „1 : X“ pro zobrazení v obchodě.
 */
export function oddsTable(profile: PackProfile): { label: string; p: number }[] {
  const rows: { label: string; p: number }[] = [];
  for (const slot of profile.slots) {
    for (const hit of slot.hits) {
      const name =
        hit.variant === "normal" ? hit.rarities.join(" / ") : `${VARIANT_LABEL[hit.variant]} (C/U/R)`;
      rows.push({ label: name, p: (hit.p ?? 0) * slot.count });
    }
  }
  return rows.sort((a, b) => b.p - a.p);
}
