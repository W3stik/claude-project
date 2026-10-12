import { cardNumber, setIdOfCard } from "../data";
import { rarityInfo, VARIANT_LABEL } from "../odds";
import { type CardPrice, formatEur, formatUsd, loadSetPrices, tcgdexPrice } from "../prices";
import { countsFor, getState } from "../store";
import type { Card, SetInfo, Variant } from "../types";
import { h } from "../ui/dom";
import { card3dViewer } from "../ui/card3d";
import { openModal } from "../ui/modal";

const dateFmt = new Intl.DateTimeFormat("cs-CZ", { dateStyle: "medium", timeStyle: "short" });

function priceBlock(price: CardPrice | undefined): HTMLElement {
  if (!price || (price.eur === undefined && price.usd === undefined)) {
    return h("p", { class: "muted" }, "Cena není k dispozici (karta je nová, nebo jsi offline).");
  }
  const row = (label: string, value: string) => h("tr", null, h("th", null, label), h("td", null, value));
  return h(
    "div",
    null,
    h(
      "table",
      { class: "prices" },
      h(
        "tbody",
        null,
        row("Cardmarket (trend)", formatEur(price.eur)),
        price.eurReverse !== undefined ? row("Cardmarket reverse holo", formatEur(price.eurReverse)) : null,
        row("TCGplayer (market)", formatUsd(price.usd)),
        price.usdReverse !== undefined ? row("TCGplayer reverse holo", formatUsd(price.usdReverse)) : null,
      ),
    ),
    h(
      "p",
      { class: "muted small" },
      `Zdroj: ${price.source}${price.updated ? `, aktualizováno ${price.updated}` : ""}. `,
      price.cardmarketUrl ? h("a", { href: price.cardmarketUrl, target: "_blank", rel: "noopener" }, "Cardmarket") : null,
      price.cardmarketUrl && price.tcgplayerUrl ? " · " : null,
      price.tcgplayerUrl ? h("a", { href: price.tcgplayerUrl, target: "_blank", rel: "noopener" }, "TCGplayer") : null,
    ),
  );
}

/** Karta ve 3D přes celou obrazovku. */
function openFullscreen(card: Card, variant: Variant, missing: boolean) {
  const viewer = card3dViewer(card, variant, { missing });
  const close = () => {
    overlay.remove();
    document.removeEventListener("keydown", onKey, { capture: true });
  };
  const onKey = (e: KeyboardEvent) => {
    if (e.key === "Escape") {
      e.stopImmediatePropagation();
      close();
    }
  };
  const overlay = h(
    "div",
    { class: "viewer", role: "dialog", "aria-modal": "true", "aria-label": `${card.name} ve 3D` },
    h("h2", { class: "viewer__title" }, card.name),
    viewer.el,
    h(
      "div",
      { class: "card3d-controls" },
      h("button", { class: "btn", onclick: () => viewer.flip() }, "↻ Otočit"),
      h("button", { class: "btn", onclick: () => viewer.reset() }, "Výchozí pohled"),
      h("button", { class: "btn btn--primary", onclick: close }, "Zavřít"),
    ),
  );
  // Esc zavře nejdřív celou obrazovku, ne detail karty pod ní.
  document.addEventListener("keydown", onKey, { capture: true });
  document.body.append(overlay);
}

export function openCardModal(card: Card, set: SetInfo) {
  const info = rarityInfo(card.rarity);
  const counts = countsFor(card.id);
  const owned = Object.entries(counts) as [Variant, number][];
  const total = owned.reduce((n, [, c]) => n + c, 0);
  const firstSeen = getState().firstSeen[card.id];
  const priceSlot = h("div", null, h("p", { class: "muted" }, "Načítám ceny…"));

  // Ve 3D ukážeme nejlepší vlastněné provedení (reverse / vzorované holo má přednost).
  const variant = owned.find(([v]) => v !== "normal")?.[0] ?? "normal";
  const viewer = card3dViewer(card, variant, { missing: total === 0 });

  const content = h(
    "div",
    { class: "card-detail" },
    h(
      "div",
      { class: "card-detail__card" },
      viewer.el,
      h(
        "div",
        { class: "card3d-controls" },
        h("button", { class: "btn", onclick: () => viewer.flip() }, "↻ Otočit"),
        h("button", { class: "btn", onclick: () => viewer.reset() }, "Výchozí pohled"),
        h("button", { class: "btn", onclick: () => openFullscreen(card, variant, total === 0) }, "⛶ Celá obrazovka"),
      ),
      h("p", { class: "card3d-hint muted" }, "Táhni kartou a otoč ji, dvojklikem ji obrátíš."),
    ),
    h(
      "div",
      { class: "card-detail__info" },
      h("h2", null, card.name),
      h(
        "p",
        null,
        h("span", { class: "rarity-dot", style: `background: ${info.color}` }),
        ` ${card.rarity}${card.printedRarity ? ` (původně ${card.printedRarity})` : ""}`,
      ),
      h(
        "p",
        { class: "muted" },
        `${set.name} · č. ${cardNumber(card)}${card.prefix ? "" : `/${set.printedTotal}`}`,
        card.artist ? ` · ilustrace ${card.artist}` : "",
      ),
      h(
        "p",
        { class: "muted" },
        [card.supertype, ...card.subtypes].join(" · "),
        card.hp ? ` · ${card.hp} HP` : "",
        card.types.length ? ` · ${card.types.join(", ")}` : "",
      ),
      h("h3", null, "Ve sbírce"),
      total
        ? h(
            "ul",
            { class: "owned-list" },
            ...owned.map(([v, c]) => h("li", null, `${VARIANT_LABEL[v]}: ${c}×`)),
            h("li", null, h("strong", null, `Celkem ${total}×`), total > 1 ? ` (${total - 1} duplikát${total - 1 === 1 ? "" : total - 1 < 5 ? "y" : "ů"})` : ""),
          )
        : h("p", { class: "muted" }, "Tuto kartu zatím nemáš."),
      firstSeen ? h("p", { class: "muted small" }, `Poprvé získána ${dateFmt.format(firstSeen)}`) : null,
      h("h3", null, "Tržní cena"),
      priceSlot,
    ),
  );
  openModal(content, "modal__box--card");

  // Nejdřív ukážeme uložené ceny, pak je zkusíme nahradit živými z TCGdex.
  loadSetPrices([setIdOfCard(card.id)])
    .then(async (prices) => {
      const stored = prices[card.id];
      if (stored) priceSlot.replaceChildren(priceBlock(stored));
      const subsetName = card.prefix ? `${set.name}: ${card.rarity}` : set.name;
      const live = await tcgdexPrice(card, subsetName);
      const hasValue = (p?: CardPrice) => p && (p.eur !== undefined || p.usd !== undefined);
      priceSlot.replaceChildren(priceBlock(hasValue(live) ? { ...stored, ...live } : stored));
    })
    .catch(() => priceSlot.replaceChildren(priceBlock(undefined)));
}
