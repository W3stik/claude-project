// Regál v obchodě: 10 balíčků sady s předem určeným obsahem, hráč si jeden vybere.
import { loadCards, loadPools, loadSets } from "../data";
import { packProfile } from "../odds";
import { fromSealed, hintLevel, openPack, toSealed } from "../pack";
import { getState, pickFromShelf, type SealedPack, setShelf } from "../store";
import type { Card, SetInfo } from "../types";
import { clear, h, toast } from "../ui/dom";
import { packEl } from "../ui/pack";

const SHELF_SIZE = 10;

export async function renderPick(root: HTMLElement, setId?: string) {
  const sets = await loadSets();
  const set = sets.find((s) => s.id === setId);
  if (!set) {
    root.append(h("p", { class: "empty" }, "Neznámá sada."));
    return;
  }
  const [cards, pools] = await Promise.all([loadCards(set.id), loadPools(set.id)]);
  const byId = new Map(cards.map((c) => [c.id, c]));
  const roll = (): SealedPack => toSealed(openPack(packProfile(set.id), pools));

  // Regál zůstává stejný i po obnovení stránky; neplatné balíčky (např. po
  // aktualizaci dat) se nahradí novými.
  let shelf = (getState().shelf[set.id] ?? []).filter((p) => fromSealed(p, byId));
  if (shelf.length !== SHELF_SIZE) {
    shelf = [...shelf, ...Array.from({ length: SHELF_SIZE }, roll)].slice(0, SHELF_SIZE);
    setShelf(set.id, shelf);
  }

  const grid = h("div", { class: "shelf" });
  const actions = h("div", { class: "shelf__actions" });
  const owned = h("span");
  let selected: number | null = null;

  const refreshOwned = () => {
    owned.textContent = `Neotevřené: ${getState().packs[set.id] ?? 0}`;
  };

  // Sloty se vytvoří jednou; výběr jen přepíná třídu, aby se animace nerestartovaly.
  const slots = (getState().shelf[set.id] ?? []).map((pack, i) => slot(set, pack, byId, i, () => select(i)));
  grid.append(...slots);

  const select = (i: number | null) => {
    selected = i !== null && selected !== i ? i : null;
    slots.forEach((el, j) => {
      el.classList.toggle("is-selected", j === selected);
      el.setAttribute("aria-pressed", String(j === selected));
    });
    renderActions();
  };

  const take = (open: boolean) => {
    if (selected === null) return;
    const index = selected;
    const replacement = roll();
    pickFromShelf(set.id, index, replacement);
    refreshOwned();
    if (open) {
      location.hash = `#/open/${set.id}`;
      return;
    }
    toast(`Balíček ${set.name} je tvůj`);
    // Na uvolněné místo přijde nový balíček.
    const fresh = slot(set, replacement, byId, index, () => select(index));
    fresh.classList.add("shelf__slot--new");
    slots[index].replaceWith(fresh);
    slots[index] = fresh;
    select(null);
  };

  const renderActions = () => {
    clear(actions);
    actions.append(
      h("button", { class: "btn btn--primary", disabled: selected === null, onclick: () => take(true) }, "Vzít a otevřít"),
      h("button", { class: "btn", disabled: selected === null, onclick: () => take(false) }, "Jen vzít"),
    );
  };

  refreshOwned();
  renderActions();
  root.append(
    h(
      "section",
      { class: "view-head" },
      h("a", { class: "back", href: "#/shop" }, "← Obchod"),
      h("div", { class: "view-head--row" }, h("h1", null, set.name), h("a", { class: "chip", href: `#/open/${set.id}` }, owned)),
      h("p", { class: "muted" }, "Vyber si jeden z balíčků na regálu. Je zdarma, ale vybrat můžeš jen jeden najednou."),
    ),
    grid,
    actions,
  );
}

function slot(
  set: SetInfo,
  pack: SealedPack,
  byId: Map<string, Card>,
  index: number,
  onSelect: () => void,
): HTMLElement {
  const cards = fromSealed(pack, byId) ?? [];
  const el = packEl(set, { tilt: true, hint: hintLevel(cards) });
  el.classList.add("pack3d--idle");
  // Každý balíček se pohupuje jinak, aby regál nepůsobil strojově.
  el.style.setProperty("--sway-delay", `${-((index * 1.7) % 5)}s`);
  return h(
    "button",
    {
      class: "shelf__slot",
      "aria-pressed": "false",
      "aria-label": `Balíček ${index + 1}`,
      onclick: onSelect,
    },
    el,
  );
}
