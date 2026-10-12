// 3D model karty s prohlížečem: líc s holo efektem, oficiální rub a tenká hrana.
// Kartou jde otáčet tažením do všech stran (i na rub), po puštění dojíždí
// setrvačností; lesk se mění podle natočení vůči „světlu“.
import type { Card, Variant } from "../types";
import { h, prefersReducedMotion } from "./dom";
import { cardBack, cardEl } from "./holo";

export interface Card3dViewer {
  el: HTMLElement;
  /** Otočí kartu o 180° (líc ↔ rub). */
  flip(): void;
  /** Vrátí kartu do výchozího pohledu. */
  reset(): void;
}

const clamp = (v: number, min: number, max: number) => Math.min(max, Math.max(min, v));

export function card3dViewer(card: Card, variant: Variant, opts: { missing?: boolean } = {}): Card3dViewer {
  const front = cardEl(card, variant, { large: true, missing: opts.missing });
  const edge = (side: string) => h("div", { class: `card3d__edge card3d__edge--${side}` });
  const body = h(
    "div",
    { class: "card3d__body" },
    h("div", { class: "card3d__face card3d__face--front" }, front),
    h("div", { class: "card3d__face card3d__face--back" }, cardBack()),
    edge("top"),
    edge("bottom"),
    edge("left"),
    edge("right"),
  );
  const el = h("div", { class: "card3d", role: "img", "aria-label": `${card.name}, 3D náhled` }, body, h("div", { class: "card3d__shadow" }));

  // Natočení karty (stupně) a rychlost pro setrvačnost.
  let rx = 0;
  let ry = 0;
  let vx = 0;
  let vy = 0;
  // Jemný pohyb podle náklonu telefonu se přičítá k natočení.
  let gx = 0;
  let gy = 0;
  let dragging = false;
  let touched = false;
  let target: { rx: number; ry: number } | null = null;
  let last = { x: 0, y: 0, t: 0 };
  let frame = 0;
  const started = performance.now();

  const render = () => {
    const x = rx + gx;
    const y = ry + gy;
    body.style.transform = `rotateX(${x}deg) rotateY(${y}deg)`;
    // Světlo je „nad divákem“: odlesk putuje proti směru natočení.
    const ly = Math.sin((y * Math.PI) / 180);
    const lx = Math.sin((x * Math.PI) / 180);
    const mx = 50 - ly * 60;
    const my = 50 + lx * 60;
    front.style.setProperty("--mx", `${mx}%`);
    front.style.setProperty("--my", `${my}%`);
    front.style.setProperty("--pos", `${mx}% ${my}%`);
    front.style.setProperty("--o", String(clamp(Math.hypot(lx, ly) * 2.2, 0.15, 1)));
    // Stín pod kartou se při náklonu zužuje.
    el.style.setProperty("--shadow-scale", String(0.55 + 0.45 * Math.abs(Math.cos((y * Math.PI) / 180))));
  };

  const tick = (now: number) => {
    frame = requestAnimationFrame(tick);
    if (!el.isConnected) {
      // Prohlížeč byl zavřen: ukončíme smyčku i poslech gyroskopu.
      cancelAnimationFrame(frame);
      window.removeEventListener("deviceorientation", onOrientation);
      return;
    }
    if (dragging) return;
    if (target) {
      // Plynulé dojetí na cílové natočení (otočení na rub, výchozí pohled).
      rx += (target.rx - rx) * 0.12;
      ry += (target.ry - ry) * 0.12;
      if (Math.abs(target.rx - rx) < 0.1 && Math.abs(target.ry - ry) < 0.1) {
        rx = target.rx;
        ry = target.ry;
        target = null;
      }
    } else if (Math.abs(vx) > 0.01 || Math.abs(vy) > 0.01) {
      // Setrvačnost po puštění.
      ry += vy;
      rx = clamp(rx + vx, -75, 75);
      vx *= 0.94;
      vy *= 0.94;
    } else if (!touched && !prefersReducedMotion()) {
      // Než na kartu sáhneš, lehce se pohupuje, aby bylo vidět, že je 3D.
      const t = (now - started) / 1000;
      ry = Math.sin(t * 0.8) * 22;
      rx = Math.sin(t * 0.6) * 6;
    }
    render();
  };

  el.addEventListener("pointerdown", (e) => {
    dragging = true;
    touched = true;
    target = null;
    vx = vy = 0;
    last = { x: e.clientX, y: e.clientY, t: performance.now() };
    el.setPointerCapture(e.pointerId);
    el.classList.add("is-dragging");
  });
  el.addEventListener("pointermove", (e) => {
    if (!dragging) return;
    const now = performance.now();
    const dx = e.clientX - last.x;
    const dy = e.clientY - last.y;
    ry += dx * 0.55;
    rx = clamp(rx - dy * 0.45, -75, 75);
    const dt = Math.max(1, now - last.t) / 16;
    vy = (dx * 0.55) / dt;
    vx = (-dy * 0.45) / dt;
    last = { x: e.clientX, y: e.clientY, t: now };
    render();
  });
  const release = () => {
    if (!dragging) return;
    dragging = false;
    el.classList.remove("is-dragging");
    // Krátký švih nechá kartu dotočit, pomalé puštění ji zastaví.
    if (performance.now() - last.t > 80) vx = vy = 0;
  };
  el.addEventListener("pointerup", release);
  el.addEventListener("pointercancel", release);
  el.addEventListener("dblclick", () => flip());

  function onOrientation(e: DeviceOrientationEvent) {
    if (e.beta === null || e.gamma === null) return;
    gy = clamp(e.gamma, -30, 30) * 0.35;
    gx = clamp(e.beta - 40, -30, 30) * -0.3;
  }
  window.addEventListener("deviceorientation", onOrientation);

  const flip = () => {
    touched = true;
    vx = vy = 0;
    // Z právě viditelné strany se otočí o půl otáčky na tu druhou.
    target = { rx: 0, ry: (Math.round(ry / 180) + 1) * 180 };
  };
  const reset = () => {
    touched = true;
    vx = vy = 0;
    target = { rx: 0, ry: Math.round(ry / 360) * 360 };
  };

  render();
  frame = requestAnimationFrame(tick);
  return { el, flip, reset };
}
