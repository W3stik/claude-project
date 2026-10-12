import { loadPools, loadSets, setIdOfCard } from "../data";
import { packProfile, rarityInfo, VARIANT_LABEL } from "../odds";
import { openPack } from "../pack";
import { type CardPrice, formatEur, formatUsd, loadSetPrices, variantPrice } from "../prices";
import { collectionKey, getState, recordOpening } from "../store";
import type { Card, PulledCard, SetInfo } from "../types";
import { animationEnd, append, clear, h, prefersReducedMotion, sleep } from "../ui/dom";
import { cardBack, cardEl, preload } from "../ui/holo";
import { packEl } from "../ui/pack";
import { openCardModal } from "./cardModal";

/** Kolik posledních karet balíčku se odhaluje lícem dolů (vzácné sloty). */
const FACE_DOWN = 3;

const priceSetIds = (cards: PulledCard[]) => [...new Set(cards.map((c) => setIdOfCard(c.card.id)))];

/** Výběr sady z neotevřených balíčků. */
async function renderInventory(root: HTMLElement) {
  const sets = await loadSets();
  const packs = getState().packs;
  const owned = sets.filter((s) => packs[s.id]);
  root.append(h("section", { class: "view-head" }, h("h1", null, "Moje balíčky")));
  if (owned.length === 0) {
    root.append(
      h(
        "div",
        { class: "empty" },
        h("p", null, "Nemáš žádné neotevřené balíčky."),
        h("a", { class: "btn btn--primary", href: "#/shop" }, "Do obchodu"),
      ),
    );
    return;
  }
  root.append(
    h(
      "div",
      { class: "inventory" },
      ...owned.map((s) =>
        h(
          "a",
          { class: "inventory__item", href: `#/open/${s.id}` },
          packEl(s),
          h("strong", null, s.name),
          h("span", { class: "chip" }, `${packs[s.id]}×`),
        ),
      ),
    ),
  );
}

export async function renderOpen(root: HTMLElement, setId?: string) {
  if (!setId) return renderInventory(root);
  const sets = await loadSets();
  const set = sets.find((s) => s.id === setId);
  if (!set) {
    root.append(h("p", { class: "empty" }, "Neznámá sada."));
    return;
  }
  const pools = await loadPools(set.id);
  new OpeningStage(root, set, pools).showPack();
}

class OpeningStage {
  private stage = h("div", { class: "stage" });
  private controls = h("div", { class: "stage__controls" });
  private remaining = h("span", { class: "chip" });

  constructor(
    root: HTMLElement,
    private set: SetInfo,
    private pools: Map<string, Card[]>,
  ) {
    root.append(
      h(
        "section",
        { class: "view-head view-head--row" },
        h("h1", null, set.name),
        this.remaining,
      ),
      this.stage,
      this.controls,
    );
  }

  private left = () => getState().packs[this.set.id] ?? 0;

  private updateRemaining() {
    this.remaining.textContent = `Zbývá: ${this.left()}`;
  }

  showPack() {
    this.updateRemaining();
    clear(this.stage);
    clear(this.controls);
    if (this.left() === 0) {
      this.stage.append(
        h(
          "div",
          { class: "empty" },
          h("p", null, "Balíčky této sady došly."),
          h("a", { class: "btn btn--primary", href: "#/shop" }, "Vzít další v obchodě"),
          h("a", { class: "btn", href: `#/album/${this.set.id}` }, "Do alba"),
        ),
      );
      return;
    }

    const pack = packEl(this.set);
    pack.classList.add("pack--big", "pack--idle");
    const cut = h("div", { class: "pack__cut" });
    pack.append(cut);
    const hint = h("p", { class: "stage__hint" }, "Přejeď prstem přes horní okraj nebo klepni na balíček");
    this.stage.append(h("div", { class: "pack-wrap" }, pack), hint);

    // Roztržení: tažení přes horní část balíčku nebo prosté klepnutí.
    let startX: number | null = null;
    let done = false;
    const once = (fn: () => void) => () => {
      if (done) return;
      done = true;
      fn();
    };
    const tear = once(() => {
      hint.remove();
      this.open(pack);
    });
    pack.addEventListener("pointerdown", (e) => {
      startX = e.clientX;
      pack.setPointerCapture(e.pointerId);
    });
    pack.addEventListener("pointermove", (e) => {
      if (startX === null) return;
      const r = pack.getBoundingClientRect();
      const progress = Math.min(1, Math.abs(e.clientX - startX) / (r.width * 0.7));
      cut.style.setProperty("--cut", String(progress));
      if (progress >= 1) tear();
    });
    pack.addEventListener("pointerup", (e) => {
      const moved = startX !== null && Math.abs(e.clientX - startX) > 8;
      startX = null;
      if (!moved) tear();
      else if (!done) cut.style.setProperty("--cut", "0");
    });

    append(this.controls, [
      h("button", { class: "btn", onclick: once(() => this.quickOpen(1)) }, "Otevřít bez animace"),
      this.left() > 1
        ? h("button", { class: "btn", onclick: once(() => this.quickOpen(this.left())) }, `Otevřít vše (${this.left()})`)
        : null,
    ]);
  }

  private draw(): { cards: PulledCard[]; fresh: Set<string> } {
    const cards = openPack(packProfile(this.set.id), this.pools);
    const fresh = recordOpening(this.set.id, cards);
    this.updateRemaining();
    return { cards, fresh };
  }

  private async open(pack: HTMLElement) {
    clear(this.controls);
    const { cards, fresh } = this.draw();
    const imagesReady = preload(cards.map((c) => c.card.img));

    pack.classList.remove("pack--idle");
    pack.classList.add("pack--torn");
    await Promise.race([Promise.all([animationEnd(pack, 900), imagesReady]), sleep(2500)]);
    this.reveal(cards, fresh);
  }

  private reveal(cards: PulledCard[], fresh: Set<string>) {
    clear(this.stage);
    const counter = h("div", { class: "stage__counter" });
    const pile = h("div", { class: "pile" });
    this.stage.append(pile, counter, h("p", { class: "stage__hint" }, "Klepni na kartu pro další"));

    const items = cards.map((pulled, i) => {
      const faceDown = i >= cards.length - FACE_DOWN;
      const info = rarityInfo(pulled.card.rarity);
      const front = cardEl(pulled.card, pulled.variant, { tilt: true });
      const isNew = fresh.has(collectionKey(pulled.card.id, pulled.variant));
      const item = h(
        "div",
        {
          class: `pile__item${faceDown ? " is-down" : ""}${info.hit ? " is-hit" : ""}`,
          style: `--rc: ${info.color}; z-index: ${cards.length - i}`,
        },
        h("div", { class: "flip" }, h("div", { class: "flip__front" }, front), h("div", { class: "flip__back" }, cardBack())),
        h(
          "div",
          { class: "pile__tag" },
          isNew ? h("span", { class: "badge badge--new" }, "NOVÁ") : null,
          pulled.variant !== "normal" ? h("span", { class: "badge" }, VARIANT_LABEL[pulled.variant]) : null,
          info.hit ? h("span", { class: "badge", style: `background: ${info.color}; color: #111` }, pulled.card.rarity) : null,
        ),
      );
      pile.append(item);
      return item;
    });

    let index = 0;
    let busy = false;
    const update = () => {
      counter.textContent = `${Math.min(index + 1, cards.length)} / ${cards.length}`;
      items.forEach((item, i) => item.classList.toggle("is-current", i === index));
    };
    update();

    const advance = async () => {
      if (busy) return;
      const item = items[index];
      if (!item) return;
      busy = true;
      if (item.classList.contains("is-down")) {
        await this.flip(item, rarityInfo(cards[index].card.rarity).rank);
      } else {
        item.classList.add("is-gone");
        index++;
        update();
        if (index >= items.length) {
          await sleep(250);
          this.summary(cards, fresh);
        }
      }
      busy = false;
    };

    pile.addEventListener("click", advance);
    this.controls.append(
      h("button", { class: "btn", onclick: () => this.summary(cards, fresh) }, "Přeskočit na přehled"),
    );
  }

  private async flip(item: HTMLElement, rank: number) {
    const hit = item.classList.contains("is-hit");
    if (hit && !prefersReducedMotion()) {
      // Napětí před odhalením: karta se rozzáří barvou rarity.
      item.classList.add("is-charging");
      await sleep(rank >= 8 ? 1100 : 600);
      item.classList.remove("is-charging");
      burst(item, rank);
      if (rank >= 8) flash();
    }
    item.classList.remove("is-down");
    item.classList.add("is-flipped");
    await sleep(450);
  }

  /** Otevře více balíčků naráz bez animace a ukáže souhrn. */
  private quickOpen(count: number) {
    const all: PulledCard[] = [];
    const fresh = new Set<string>();
    for (let i = 0; i < count && this.left() > 0; i++) {
      const r = this.draw();
      all.push(...r.cards);
      r.fresh.forEach((k) => fresh.add(k));
    }
    this.summary(all, fresh, count);
  }

  private summary(cards: PulledCard[], fresh: Set<string>, packs = 1) {
    clear(this.stage);
    clear(this.controls);
    this.updateRemaining();

    // Stejné karty ve stejném provedení se seskupí (×N). U jednoho balíčku
    // zůstává pořadí, v jakém karty padly, u více balíčků řadíme od nejvzácnější.
    const groups = new Map<string, { pulled: PulledCard; count: number }>();
    for (const pulled of cards) {
      const key = collectionKey(pulled.card.id, pulled.variant);
      const g = groups.get(key);
      if (g) g.count++;
      else groups.set(key, { pulled, count: 1 });
    }
    const entries = [...groups.values()];
    if (packs > 1) {
      entries.sort(
        (a, b) =>
          rarityInfo(b.pulled.card.rarity).rank - rarityInfo(a.pulled.card.rarity).rank ||
          a.pulled.card.number - b.pulled.card.number,
      );
    }
    const hits = entries.filter((e) => rarityInfo(e.pulled.card.rarity).hit);

    const total = h("strong", null, "načítám ceny…");
    const grid = h("div", { class: "summary__grid" });
    let prices: Record<string, CardPrice> | null = null;
    let priceEls: { el: HTMLElement; pulled: PulledCard }[] = [];

    const priceText = (pulled: PulledCard) => {
      if (!prices) return "";
      const p = variantPrice(prices[pulled.card.id], pulled.variant);
      return p.eur !== undefined ? formatEur(p.eur) : p.usd !== undefined ? formatUsd(p.usd) : "";
    };

    const tile = ({ pulled, count }: { pulled: PulledCard; count: number }) => {
      const price = h("span", { class: "summary__price" }, priceText(pulled));
      priceEls.push({ el: price, pulled });
      return h(
        "button",
        { class: "summary__item", onclick: () => openCardModal(pulled.card, this.set) },
        cardEl(pulled.card, pulled.variant),
        count > 1 ? h("span", { class: "count-badge" }, `×${count}`) : null,
        h(
          "div",
          { class: "summary__meta" },
          h("span", { class: "rarity-chip", style: `--rc: ${rarityInfo(pulled.card.rarity).color}` }, rarityInfo(pulled.card.rarity).short),
          fresh.has(collectionKey(pulled.card.id, pulled.variant)) ? h("span", { class: "badge badge--new" }, "NOVÁ") : null,
          pulled.variant !== "normal" ? h("span", { class: "badge" }, VARIANT_LABEL[pulled.variant]) : null,
          price,
        ),
      );
    };

    let showAll = packs === 1;
    const toggle = h("button", { class: "btn btn--ghost" });
    const renderGrid = () => {
      const list = showAll ? entries : hits;
      priceEls = [];
      grid.replaceChildren(...list.map(tile));
      if (list.length === 0) grid.append(h("p", { class: "muted" }, "Tentokrát žádná vzácná karta."));
      toggle.textContent = showAll ? "Jen vzácné karty" : `Zobrazit všechny karty (${entries.length})`;
    };
    toggle.addEventListener("click", () => {
      showAll = !showAll;
      renderGrid();
    });
    renderGrid();

    this.stage.append(
      h(
        "div",
        { class: "summary" },
        h(
          "div",
          { class: "summary__head" },
          h("h2", null, packs > 1 ? `Otevřeno ${packs} balíčků` : "Tvůj balíček"),
          h("p", null, `${cards.length} karet · ${fresh.size} nových do sbírky · hodnota `, total),
          packs > 1 ? h("div", { class: "row" }, h("span", { class: "muted" }, `Vzácných karet: ${hits.reduce((n, e) => n + e.count, 0)}`), toggle) : null,
        ),
        grid,
      ),
    );

    this.controls.append(
      this.left() > 0
        ? h("button", { class: "btn btn--primary", onclick: () => this.showPack() }, `Otevřít další (${this.left()})`)
        : h("a", { class: "btn btn--primary", href: "#/shop" }, "Vzít další balíčky"),
      h("a", { class: "btn", href: `#/album/${this.set.id}` }, "Do alba"),
    );

    loadSetPrices(priceSetIds(cards)).then((loaded) => {
      prices = loaded;
      let eur = 0;
      let usd = 0;
      for (const pulled of cards) {
        const p = variantPrice(loaded[pulled.card.id], pulled.variant);
        eur += p.eur ?? 0;
        usd += p.usd ?? 0;
      }
      total.textContent = eur || usd ? `${formatEur(eur)} (Cardmarket) · ${formatUsd(usd)} (TCGplayer)` : "ceny nejsou dostupné";
      for (const { el, pulled } of priceEls) el.textContent = priceText(pulled);
    });
  }
}

/** Záblesk částic kolem karty v barvě rarity. */
function burst(item: HTMLElement, rank: number) {
  const n = rank >= 8 ? 28 : 16;
  const layer = h("div", { class: "burst" });
  for (let i = 0; i < n; i++) {
    const angle = (360 / n) * i + Math.random() * 10;
    const dist = 120 + Math.random() * (rank >= 8 ? 160 : 80);
    layer.append(h("i", { style: `--a: ${angle}deg; --d: ${dist}px; --t: ${0.5 + Math.random() * 0.5}s` }));
  }
  item.append(layer);
  setTimeout(() => layer.remove(), 1200);
}

function flash() {
  const el = h("div", { class: "flash" });
  document.body.append(el);
  setTimeout(() => el.remove(), 700);
}
