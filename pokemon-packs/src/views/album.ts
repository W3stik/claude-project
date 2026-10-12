import { cardNumber, loadCards, loadSets, setIdOfCard } from "../data";
import { RARITIES, rarityInfo } from "../odds";
import { type CardPrice, formatEur, formatUsd, loadSetPrices, sortValue, variantPrice } from "../prices";
import { countsFor, getState } from "../store";
import type { Card, SetInfo, Variant } from "../types";
import { h } from "../ui/dom";
import { cardEl } from "../ui/holo";
import { openCardModal } from "./cardModal";

type Filter = "all" | "owned" | "missing" | "dupes";
type Sort = "number" | "rarity" | "name" | "price" | "count";

interface Prefs {
  filter: Filter;
  sort: Sort;
  rarity: string;
}

const PREFS_KEY = "pokemon-packs:album-prefs";
const defaultPrefs: Prefs = { filter: "all", sort: "number", rarity: "" };

function loadPrefs(): Prefs {
  try {
    return { ...defaultPrefs, ...JSON.parse(localStorage.getItem(PREFS_KEY) ?? "{}") };
  } catch {
    return { ...defaultPrefs };
  }
}

function savePrefs(p: Prefs) {
  try {
    localStorage.setItem(PREFS_KEY, JSON.stringify(p));
  } catch {
    // nevadí
  }
}

const pct = new Intl.NumberFormat("cs-CZ", { style: "percent", maximumFractionDigits: 0 });
const VARIANT_SHORT: Record<Variant, string> = { normal: "", reverse: "RH", pokeball: "PB", masterball: "MB" };

interface Owned {
  card: Card;
  counts: Partial<Record<Variant, number>>;
  total: number;
}

function ownedOf(cards: Card[]): Owned[] {
  return cards.map((card) => {
    const counts = countsFor(card.id);
    const total = Object.values(counts).reduce((a, b) => a + (b ?? 0), 0);
    return { card, counts, total };
  });
}

/** Hodnota všech vlastněných kusů (včetně duplikátů). */
function collectionValue(owned: Owned[], prices: Record<string, CardPrice>) {
  let eur = 0;
  let usd = 0;
  for (const o of owned) {
    for (const [variant, n] of Object.entries(o.counts) as [Variant, number][]) {
      const p = variantPrice(prices[o.card.id], variant);
      eur += (p.eur ?? 0) * n;
      usd += (p.usd ?? 0) * n;
    }
  }
  return { eur, usd };
}

const priceIds = (cards: Card[]) => [...new Set(cards.map((c) => setIdOfCard(c.id)))];

function stats(owned: Owned[]) {
  const unique = owned.filter((o) => o.total > 0).length;
  const dupeCards = owned.filter((o) => o.total > 1).length;
  const extra = owned.reduce((n, o) => n + Math.max(0, o.total - 1), 0);
  const copies = owned.reduce((n, o) => n + o.total, 0);
  return { unique, dupeCards, extra, copies, total: owned.length };
}

function progress(value: number) {
  return h("div", { class: "progress" }, h("div", { class: "progress__bar", style: `width: ${value * 100}%` }));
}

// --- Přehled všech sad -----------------------------------------------------

async function renderOverview(root: HTMLElement) {
  const sets = await loadSets();
  const perSet = await Promise.all(sets.map(async (s) => ({ set: s, owned: ownedOf(await loadCards(s.id)) })));

  const all = perSet.flatMap((p) => p.owned);
  const st = stats(all);
  const valueEl = h("strong", null, "…");
  const opened = Object.values(getState().opened).reduce((a, b) => a + b, 0);

  root.append(
    h("section", { class: "view-head" }, h("h1", null, "Sběratelské album")),
    h(
      "div",
      { class: "stats" },
      h("div", null, h("span", null, "Unikátních karet"), h("strong", null, `${st.unique} / ${st.total}`)),
      h("div", null, h("span", null, "Kusů celkem"), h("strong", null, String(st.copies))),
      h("div", null, h("span", null, "Duplikáty"), h("strong", null, `${st.extra}`)),
      h("div", null, h("span", null, "Otevřeno balíčků"), h("strong", null, String(opened))),
      h("div", { class: "stats__wide" }, h("span", null, "Hodnota sbírky"), valueEl),
    ),
    h(
      "div",
      { class: "album-sets" },
      ...perSet.map(({ set, owned }) => {
        const s = stats(owned);
        return h(
          "a",
          { class: "album-set", href: `#/album/${set.id}` },
          h("img", { src: set.logo, alt: set.name, loading: "lazy" }),
          h("div", null, h("strong", null, set.name), h("span", { class: "muted" }, ` ${s.unique}/${s.total} · ${pct.format(s.unique / s.total)}`)),
          progress(s.unique / s.total),
          s.extra ? h("span", { class: "muted small" }, `${s.extra} duplikátů`) : null,
        );
      }),
    ),
  );

  const ownedSets = perSet.filter((p) => p.owned.some((o) => o.total > 0));
  if (ownedSets.length === 0) {
    valueEl.textContent = formatEur(0);
    return;
  }
  const prices = await loadSetPrices(ownedSets.flatMap((p) => priceIds(p.owned.map((o) => o.card))));
  const v = collectionValue(all, prices);
  valueEl.textContent = `${formatEur(v.eur)} · ${formatUsd(v.usd)}`;
}

// --- Album jedné sady ------------------------------------------------------

function sortOwned(list: Owned[], sort: Sort, prices: Record<string, CardPrice>) {
  const byNumber = (a: Owned, b: Owned) =>
    (a.card.prefix ?? "").localeCompare(b.card.prefix ?? "") || a.card.number - b.card.number;
  const cmp: Record<Sort, (a: Owned, b: Owned) => number> = {
    number: byNumber,
    rarity: (a, b) => rarityInfo(b.card.rarity).rank - rarityInfo(a.card.rarity).rank || byNumber(a, b),
    name: (a, b) => a.card.name.localeCompare(b.card.name, "cs") || byNumber(a, b),
    price: (a, b) =>
      sortValue(variantPrice(prices[b.card.id], "normal")) - sortValue(variantPrice(prices[a.card.id], "normal")) ||
      byNumber(a, b),
    count: (a, b) => b.total - a.total || byNumber(a, b),
  };
  return [...list].sort(cmp[sort]);
}

function tile(o: Owned, set: SetInfo, prices: Record<string, CardPrice>): HTMLElement {
  const info = rarityInfo(o.card.rarity);
  const variants = (Object.keys(o.counts) as Variant[]).filter((v) => v !== "normal");
  const shown = variants[0] ?? "normal";
  const price = variantPrice(prices[o.card.id], "normal");
  return h(
    "button",
    { class: `album-tile${o.total ? "" : " album-tile--missing"}`, onclick: () => openCardModal(o.card, set) },
    cardEl(o.card, shown, { missing: o.total === 0 }),
    o.total > 1 ? h("span", { class: "count-badge", title: `${o.total - 1} duplikátů` }, `×${o.total}`) : null,
    h(
      "div",
      { class: "album-tile__meta" },
      h("span", { class: "rarity-chip", style: `--rc: ${info.color}` }, info.short),
      h("span", null, `#${cardNumber(o.card)}`),
      ...variants.map((v) => h("span", { class: "variant-chip" }, VARIANT_SHORT[v])),
      price.eur !== undefined || price.usd !== undefined
        ? h("span", { class: "album-tile__price" }, price.eur !== undefined ? formatEur(price.eur) : formatUsd(price.usd))
        : null,
    ),
  );
}

function select<T extends string>(label: string, value: T, options: [T, string][], onChange: (v: T) => void) {
  const el = h(
    "select",
    { "aria-label": label, onchange: (e: Event) => onChange((e.target as HTMLSelectElement).value as T) },
    ...options.map(([v, text]) => h("option", { value: v, selected: v === value }, text)),
  );
  return h("label", { class: "field" }, h("span", null, label), el);
}

async function renderSetAlbum(root: HTMLElement, setId: string) {
  const sets = await loadSets();
  const set = sets.find((s) => s.id === setId);
  if (!set) {
    root.append(h("p", { class: "empty" }, "Neznámá sada."));
    return;
  }
  const cards = await loadCards(set.id);
  const owned = ownedOf(cards);
  const st = stats(owned);
  const prefs = loadPrefs();
  let query = "";
  let prices: Record<string, CardPrice> = {};

  const valueEl = h("strong", null, "…");
  const grid = h("div", { class: "album-grid" });
  const countEl = h("span", { class: "muted" });

  const rarities = [...new Set(cards.map((c) => c.rarity))].sort(
    (a, b) => (RARITIES[a]?.rank ?? 0) - (RARITIES[b]?.rank ?? 0),
  );

  if (!rarities.includes(prefs.rarity)) prefs.rarity = "";

  const render = () => {
    savePrefs(prefs);
    const q = query.trim().toLowerCase();
    const list = owned.filter((o) => {
      if (prefs.rarity && o.card.rarity !== prefs.rarity) return false;
      if (prefs.filter === "owned" && o.total === 0) return false;
      if (prefs.filter === "missing" && o.total > 0) return false;
      if (prefs.filter === "dupes" && o.total < 2) return false;
      if (q && !o.card.name.toLowerCase().includes(q) && cardNumber(o.card).toLowerCase() !== q) return false;
      return true;
    });
    countEl.textContent = `${list.length} karet`;
    grid.replaceChildren(...sortOwned(list, prefs.sort, prices).map((o) => tile(o, set, prices)));
    if (list.length === 0) grid.append(h("p", { class: "empty" }, "Žádná karta neodpovídá filtru."));
  };

  root.append(
    h(
      "section",
      { class: "album-head" },
      h("a", { class: "back", href: "#/album" }, "← Všechny sady"),
      h("img", { class: "album-head__logo", src: set.logo, alt: set.name }),
      h(
        "div",
        { class: "stats" },
        h("div", null, h("span", null, "Sesbíráno"), h("strong", null, `${st.unique} / ${st.total} (${pct.format(st.unique / st.total)})`)),
        h("div", null, h("span", null, "Duplikáty"), h("strong", null, `${st.dupeCards} karet · ${st.extra} kusů navíc`)),
        h("div", null, h("span", null, "Otevřeno balíčků"), h("strong", null, String(getState().opened[set.id] ?? 0))),
        h("div", null, h("span", null, "Hodnota"), valueEl),
      ),
      progress(st.unique / st.total),
    ),
    h(
      "div",
      { class: "toolbar" },
      h(
        "label",
        { class: "field field--grow" },
        h("span", null, "Hledat"),
        h("input", {
          type: "search",
          placeholder: "Jméno nebo číslo",
          oninput: (e: Event) => {
            query = (e.target as HTMLInputElement).value;
            render();
          },
        }),
      ),
      select<Filter>("Zobrazit", prefs.filter, [["all", "Vše"], ["owned", "Mám"], ["missing", "Chybí"], ["dupes", "Duplikáty"]], (v) => {
        prefs.filter = v;
        render();
      }),
      select<string>("Rarita", prefs.rarity, [["", "Všechny"], ...rarities.map((r): [string, string] => [r, r])], (v) => {
        prefs.rarity = v;
        render();
      }),
      select<Sort>(
        "Řadit",
        prefs.sort,
        [["number", "Podle čísla"], ["rarity", "Podle rarity"], ["name", "Podle jména"], ["price", "Podle ceny"], ["count", "Podle počtu kusů"]],
        (v) => {
          prefs.sort = v;
          render();
        },
      ),
      countEl,
    ),
    grid,
  );
  render();

  prices = await loadSetPrices(priceIds(cards));
  const v = collectionValue(owned, prices);
  valueEl.textContent = `${formatEur(v.eur)} · ${formatUsd(v.usd)}`;
  if (grid.isConnected) render();
}

export async function renderAlbum(root: HTMLElement, setId?: string) {
  return setId ? renderSetAlbum(root, setId) : renderOverview(root);
}
