// Karta s holo efektem: lesk a odlesk se pohybují podle kurzoru, prstu
// nebo náklonu telefonu (gyroskop).
import { rarityInfo } from "../odds";
import type { Card, Variant } from "../types";
import { h } from "./dom";

const tilted = new Set<HTMLElement>();
let gyroListening = false;

function setTilt(el: HTMLElement, x: number, y: number, active: boolean) {
  // x, y v rozsahu 0–1 (střed = 0,5)
  el.style.setProperty("--mx", `${x * 100}%`);
  el.style.setProperty("--my", `${y * 100}%`);
  el.style.setProperty("--rx", `${(0.5 - y) * 22}deg`);
  el.style.setProperty("--ry", `${(x - 0.5) * 26}deg`);
  el.style.setProperty("--pos", `${x * 100}% ${y * 100}%`);
  el.style.setProperty("--o", active ? "1" : "0");
  el.style.setProperty("--hyp", `${Math.min(1, Math.hypot(x - 0.5, y - 0.5) * 2)}`);
}

function onOrientation(e: DeviceOrientationEvent) {
  if (e.beta === null || e.gamma === null) return;
  // Telefon držený v ruce mívá beta kolem 40°, proto střed posuneme.
  const x = Math.min(1, Math.max(0, 0.5 + e.gamma / 50));
  const y = Math.min(1, Math.max(0, 0.5 + (e.beta - 40) / 50));
  for (const el of tilted) {
    if (!el.isConnected) {
      tilted.delete(el);
      continue;
    }
    if (el.dataset.pointer === "1") continue;
    setTilt(el, x, y, true);
  }
}

function listenGyro() {
  if (gyroListening || !("DeviceOrientationEvent" in window)) return;
  gyroListening = true;
  window.addEventListener("deviceorientation", onOrientation);
}

/**
 * Zapne naklápění a pohyb lesku pro danou kartu. Bez gyroskopu jen podle
 * kurzoru (vhodné pro mřížky se stovkami karet).
 */
export function enableTilt(el: HTMLElement, { gyro = true }: { gyro?: boolean } = {}) {
  setTilt(el, 0.5, 0.5, false);
  if (gyro) {
    tilted.add(el);
    listenGyro();
  }

  el.addEventListener("pointermove", (e) => {
    const r = el.getBoundingClientRect();
    el.dataset.pointer = "1";
    setTilt(el, (e.clientX - r.left) / r.width, (e.clientY - r.top) / r.height, true);
  });
  el.addEventListener("pointerleave", () => {
    el.dataset.pointer = "0";
    setTilt(el, 0.5, 0.5, false);
  });
}

export interface CardElOptions {
  large?: boolean;
  tilt?: boolean;
  /** Naklánět i podle náklonu telefonu (výchozí ano). */
  gyro?: boolean;
  missing?: boolean;
}

/** Obrázek karty s vrstvami pro lesk podle rarity a provedení. */
export function cardEl(card: Card, variant: Variant, opts: CardElOptions = {}): HTMLElement {
  const info = rarityInfo(card.rarity);
  // Reverse holo se leskne i u běžných karet, normální Common/Uncommon ne.
  const shine = variant !== "normal" && info.shine === "none" ? "holo" : info.shine;
  const el = h(
    "div",
    {
      class: `pcard shine-${shine} variant-${variant}${opts.missing ? " pcard--missing" : ""}`,
      style: `--rc: ${info.color}`,
    },
    h(
      "div",
      { class: "pcard__inner" },
      h("img", {
        class: "pcard__img",
        src: opts.large ? card.imgLarge : card.img,
        alt: `${card.name} (${card.rarity})`,
        loading: opts.large ? "eager" : "lazy",
        decoding: "async",
        draggable: "false",
      }),
      h("div", { class: "pcard__shine" }),
      h("div", { class: "pcard__glare" }),
    ),
  );
  if (opts.tilt) enableTilt(el, { gyro: opts.gyro });
  return el;
}

/** Oficiální rub karty Pokémon TCG (načítá se z tcg.pokemon.com). */
export const CARD_BACK_URL = "https://tcg.pokemon.com/assets/img/global/tcg-card-back-2x.jpg";

/** Rub karty: oficiální obrázek, a když se nenačte, vlastní náhradní design. */
export function cardBack(): HTMLElement {
  const back = h("div", { class: "pback pback--photo" });
  const img = h("img", { class: "pback__img", src: CARD_BACK_URL, alt: "", draggable: "false" });
  img.addEventListener("error", () => {
    img.remove();
    back.classList.remove("pback--photo");
    back.append(h("div", { class: "pback__ring" }), h("div", { class: "pback__label" }, "BOOSTER LAB"));
  });
  back.append(img);
  return back;
}

/** Načte obrázky dopředu, aby se při odhalování neobjevovaly postupně. */
export function preload(urls: string[]): Promise<void> {
  return Promise.all(
    urls.map(
      (src) =>
        new Promise<void>((resolve) => {
          const img = new Image();
          img.onload = img.onerror = () => resolve();
          img.src = src;
        }),
    ),
  ).then(() => undefined);
}
