import { loadCards, loadPools, loadSets, setIdOfCard } from "../data";
import { packProfile, rarityInfo, VARIANT_LABEL } from "../odds";
import { fromSealed, hintLevel, openPack } from "../pack";
import { addPrice, type CardPrice, formatEur, formatTotal, formatUsd, loadSetPrices, type PriceTotal, variantPrice } from "../prices";
import { collectionKey, getState, nextSealed, recordOpening } from "../store";
import type { Card, PulledCard, SetInfo } from "../types";
import { animationEnd, append, clear, h, prefersReducedMotion, sleep } from "../ui/dom";
import { CARD_BACK_URL, cardBack, cardEl, enableTilt, preload } from "../ui/holo";
import { packEl } from "../ui/pack";
import { openCardModal } from "./cardModal";

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
          packEl(s, { tilt: true }),
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
  const [pools, cards] = await Promise.all([loadPools(set.id), loadCards(set.id)]);
  new OpeningStage(root, set, pools, new Map(cards.map((c) => [c.id, c]))).showPack();
}

class OpeningStage {
  private stage = h("div", { class: "stage" });
  private controls = h("div", { class: "stage__controls" });
  private remaining = h("span", { class: "chip" });

  constructor(
    root: HTMLElement,
    private set: SetInfo,
    private pools: Map<string, Card[]>,
    private byId: Map<string, Card>,
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

    // Balíček vybraný z regálu má obsah daný předem (a s ním i tajný náznak).
    const sealed = this.sealedCards();
    const pack = packEl(this.set, { large: true, tilt: true, hint: sealed ? hintLevel(sealed) : 0 });
    pack.classList.add("pack3d--big", "pack3d--idle");
    const cut = h("div", { class: "pack3d__cut" });
    pack.querySelector(".pack3d__body")!.append(cut);
    const hint = h("p", { class: "stage__hint" }, "Přejeď prstem přes horní okraj, nebo klepni. Tažením jinde balíčkem otočíš.");
    this.stage.append(h("div", { class: "pack-wrap" }, pack), hint);

    // Tažení přes horní pruh balíček roztrhne, tažení jinde jím otáčí ve 3D,
    // prosté klepnutí ho otevře.
    let drag: { x: number; mode: "tear" | "spin" } | null = null;
    let done = false;
    const once = (fn: () => void) => () => {
      if (done) return;
      done = true;
      fn();
    };
    const tear = once(() => {
      hint.remove();
      pack.classList.remove("is-dragging");
      pack.style.setProperty("--spin", "0deg");
      this.open(pack);
    });
    pack.addEventListener("pointerdown", (e) => {
      const r = pack.getBoundingClientRect();
      drag = { x: e.clientX, mode: e.clientY - r.top < r.height * 0.3 ? "tear" : "spin" };
      pack.classList.add("is-dragging");
      pack.setPointerCapture(e.pointerId);
    });
    pack.addEventListener("pointermove", (e) => {
      if (!drag || done) return;
      const dx = e.clientX - drag.x;
      if (drag.mode === "spin") {
        pack.style.setProperty("--spin", `${dx * 0.9}deg`);
        return;
      }
      const progress = Math.min(1, Math.abs(dx) / (pack.getBoundingClientRect().width * 0.7));
      cut.style.setProperty("--cut", String(progress));
      if (progress >= 1) tear();
    });
    const release = (e: PointerEvent) => {
      if (!drag) return;
      const moved = Math.abs(e.clientX - drag.x) > 8;
      drag = null;
      pack.classList.remove("is-dragging");
      if (done) return;
      if (!moved) tear();
      else {
        cut.style.setProperty("--cut", "0");
        pack.style.setProperty("--spin", "0deg");
      }
    };
    pack.addEventListener("pointerup", release);
    pack.addEventListener("pointercancel", release);

    append(this.controls, [
      h("button", { class: "btn", onclick: once(() => this.quickOpen(1)) }, "Otevřít bez animace"),
      this.left() > 1
        ? h("button", { class: "btn", onclick: once(() => this.quickOpen(this.left())) }, `Otevřít vše (${this.left()})`)
        : null,
    ]);
  }

  /** Obsah dalšího balíčku vybraného z regálu, pokud nějaký čeká. */
  private sealedCards(): PulledCard[] | null {
    const next = nextSealed(this.set.id);
    return next ? fromSealed(next, this.byId) : null;
  }

  private draw(): { cards: PulledCard[]; fresh: Set<string> } {
    const cards = this.sealedCards() ?? openPack(packProfile(this.set.id), this.pools);
    const fresh = recordOpening(this.set.id, cards);
    this.updateRemaining();
    return { cards, fresh };
  }

  private async open(pack: HTMLElement) {
    clear(this.controls);
    const { cards, fresh } = this.draw();
    const imagesReady = preload([...cards.map((c) => c.card.img), CARD_BACK_URL]);

    pack.classList.remove("pack3d--idle");
    pack.classList.add("pack3d--torn");
    const main = pack.querySelector(".pack3d__piece--main")!;
    await Promise.race([Promise.all([animationEnd(main, 1400), imagesReady]), sleep(2600)]);
    this.reveal(cards, fresh);
  }

  private reveal(cards: PulledCard[], fresh: Set<string>) {
    clear(this.stage);
    const counter = h("div", { class: "stage__counter" });
    const stack = h("div", { class: "pile__stack" });
    const pile = h("div", { class: "pile" }, stack);
    enableTilt(pile);
    this.stage.append(pile, counter, h("p", { class: "stage__hint" }, "Klepni na kartu, nebo ji odhoď do strany"));

    const items = cards.map((pulled, i) => {
      const info = rarityInfo(pulled.card.rarity);
      const front = cardEl(pulled.card, pulled.variant, { tilt: true });
      const isNew = fresh.has(collectionKey(pulled.card.id, pulled.variant));
      // Karty v balíčku nejsou srovnané úplně přesně: lehké pootočení a hloubka.
      const rot = ((i * 37) % 7) - 3;
      const item = h(
        "div",
        {
          class: `pile__item${info.hit ? " is-hit" : ""}`,
          style: `--rc: ${info.color}; --i: ${i}; --z: ${-i * 3}px; --rot: ${rot * 0.6}deg; z-index: ${cards.length - i}`,
        },
        h(
          "div",
          { class: "flip" },
          h("div", { class: "flip__front" }, front),
          h("div", { class: "flip__back" }, cardBack()),
        ),
        h(
          "div",
          { class: "pile__tag" },
          isNew ? h("span", { class: "badge badge--new" }, "NOVÁ") : null,
          pulled.variant !== "normal" ? h("span", { class: "badge" }, VARIANT_LABEL[pulled.variant]) : null,
          info.hit ? h("span", { class: "badge", style: `background: ${info.color}; color: #111` }, pulled.card.rarity) : null,
        ),
      );
      stack.append(item);
      return item;
    });

    let index = 0;
    let busy = false;
    const update = () => {
      counter.textContent = `${Math.min(index + 1, cards.length)} / ${cards.length}`;
      items.forEach((item, i) => item.classList.toggle("is-current", i === index));
    };
    update();
    // Vzácná karta hned navrchu (výjimečně) se rozzáří po vyjetí z balíčku.
    if (items[0]?.classList.contains("is-hit")) {
      setTimeout(() => this.revealHit(items[0], rarityInfo(cards[0].card.rarity).rank), 700);
    }

    const throwAway = async (item: HTMLElement, dir: number) => {
      item.style.setProperty("--dir", String(dir));
      item.classList.add("is-gone");
      index++;
      update();
      const next = items[index];
      if (next?.classList.contains("is-hit")) this.revealHit(next, rarityInfo(cards[index].card.rarity).rank);
      if (index >= items.length) {
        await sleep(300);
        this.summary(cards, fresh);
      }
    };

    const advance = async () => {
      if (busy) return;
      const item = items[index];
      if (!item) return;
      busy = true;
      await throwAway(item, -1);
      busy = false;
    };

    // Odhozování karty tažením: karta se při tom naklání ve 3D.
    let drag: { x: number; item: HTMLElement } | null = null;
    let dx = 0;
    pile.addEventListener("pointerdown", (e) => {
      const item = items[index];
      if (busy || !item) return;
      drag = { x: e.clientX, item };
      dx = 0;
      pile.setPointerCapture(e.pointerId);
    });
    pile.addEventListener("pointermove", (e) => {
      if (!drag) return;
      dx = e.clientX - drag.x;
      drag.item.classList.add("is-dragging");
      drag.item.style.transform = `translate3d(${dx}px, ${-Math.abs(dx) * 0.08}px, 40px) rotateY(${dx * 0.15}deg) rotateZ(${dx * 0.05}deg)`;
    });
    const release = () => {
      if (!drag) return;
      const { item } = drag;
      drag = null;
      item.classList.remove("is-dragging");
      item.style.transform = "";
      if (Math.abs(dx) > 70 && !busy) throwAway(item, Math.sign(dx));
      else if (Math.abs(dx) < 8) advance();
    };
    pile.addEventListener("pointerup", release);
    pile.addEventListener("pointercancel", release);

    this.controls.append(
      h("button", { class: "btn", onclick: () => this.summary(cards, fresh) }, "Přeskočit na přehled"),
    );
  }

  /** Vzácná karta se po odhalení rozzáří barvou rarity a vybuchne částicemi. */
  private revealHit(item: HTMLElement, rank: number) {
    item.classList.add("is-revealed");
    if (prefersReducedMotion()) return;
    burst(item, rank);
    if (rank >= 8) flash();
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
      const sum: PriceTotal = {};
      for (const pulled of cards) addPrice(sum, variantPrice(loaded[pulled.card.id], pulled.variant));
      total.textContent = formatTotal(sum, true);
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
