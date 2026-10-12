import { loadSets } from "../data";
import { oddsTable, packProfile, packSize } from "../odds";
import { addPacks, getState } from "../store";
import type { SetInfo } from "../types";
import { h, toast } from "../ui/dom";
import { openModal } from "../ui/modal";
import { formatDate, packEl } from "../ui/pack";

const PRODUCTS = [
  { label: "1 balíček", count: 1 },
  { label: "10 balíčků", count: 10 },
  { label: "Booster box (36)", count: 36 },
];

const pct = new Intl.NumberFormat("cs-CZ", { style: "percent", maximumFractionDigits: 2 });
const oneIn = (p: number) => (p >= 0.5 ? "téměř každý" : `1 : ${Math.round(1 / p).toLocaleString("cs-CZ")}`);

export function showOdds(set: SetInfo) {
  const profile = packProfile(set.id);
  const rows = oddsTable(profile);
  const content = h(
    "div",
    { class: "odds" },
    h("h2", null, `Šance – ${set.name}`),
    h(
      "p",
      { class: "muted" },
      "Šance na balíček. Pokémon je oficiálně nezveřejňuje, jde o měření z tisíců otevřených balíčků (TCGplayer) a komunitní statistiky.",
    ),
    h(
      "table",
      { class: "odds__table" },
      h("thead", null, h("tr", null, h("th", null, "Rarita"), h("th", null, "Šance"), h("th", null, "Na balíček"))),
      h(
        "tbody",
        null,
        ...rows.map((r) => h("tr", null, h("td", null, r.label), h("td", null, oneIn(r.p)), h("td", null, pct.format(r.p)))),
      ),
    ),
    h("h3", null, `Složení balíčku (${packSize(profile)} karet)`),
    h(
      "ol",
      { class: "odds__slots" },
      ...profile.slots.map((s) => h("li", null, s.count > 1 ? `${s.count}× ${s.label}` : s.label)),
    ),
    profile.note ? h("p", { class: "odds__note" }, profile.note) : null,
    profile.sources.length
      ? h(
          "div",
          { class: "odds__sources" },
          h("h3", null, "Zdroje"),
          h(
            "ul",
            null,
            ...profile.sources.map((s) => h("li", null, h("a", { href: s.url, target: "_blank", rel: "noopener" }, s.label))),
          ),
        )
      : null,
  );
  openModal(content, "modal__box--wide");
}

function setTile(set: SetInfo): HTMLElement {
  const owned = () => getState().packs[set.id] ?? 0;
  const ownedEl = h("span", { class: "chip" });
  const openBtn = h("a", { class: "btn btn--primary", href: `#/open/${set.id}` }, "Otevřít");
  const refresh = () => {
    ownedEl.textContent = `Neotevřené: ${owned()}`;
    openBtn.classList.toggle("hidden", owned() === 0);
  };
  refresh();

  return h(
    "article",
    { class: "shop-tile" },
    h("div", { class: "shop-tile__pack" }, packEl(set, { tilt: true })),
    h(
      "div",
      { class: "shop-tile__body" },
      h("h2", null, set.name),
      h(
        "p",
        { class: "muted" },
        `${set.series} · ${formatDate(set.releaseDate)} · ${set.total} karet`,
      ),
      h(
        "div",
        { class: "shop-tile__buy" },
        ...PRODUCTS.map((p) =>
          h(
            "button",
            {
              class: "btn",
              onclick: () => {
                addPacks(set.id, p.count);
                refresh();
                toast(`+${p.count} × ${set.name} (zdarma)`);
              },
            },
            h("span", null, p.label),
            h("small", null, "Zdarma"),
          ),
        ),
      ),
      h(
        "div",
        { class: "shop-tile__footer" },
        ownedEl,
        h("button", { class: "btn btn--ghost", onclick: () => showOdds(set) }, "Šance a zdroje"),
        openBtn,
      ),
    ),
  );
}

export async function renderShop(root: HTMLElement) {
  const sets = await loadSets();
  root.append(
    h(
      "section",
      { class: "view-head" },
      h("h1", null, "Obchod"),
      h("p", { class: "muted" }, "Posledních 10 vydaných sad. Všechny balíčky jsou zdarma, vezmi si kolik chceš."),
    ),
    h("div", { class: "shop-grid" }, ...sets.map(setTile)),
  );
}
