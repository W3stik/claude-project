type Child = Node | string | number | null | undefined | false;

interface Props {
  class?: string;
  style?: string;
  dataset?: Record<string, string>;
  [attr: string]: unknown;
}

/** Malý pomocník na tvorbu elementů: h("div", { class: "x", onclick: fn }, "text", child). */
export function h<K extends keyof HTMLElementTagNameMap>(
  tag: K,
  props: Props | null = null,
  ...children: Child[]
): HTMLElementTagNameMap[K] {
  const el = document.createElement(tag);
  for (const [key, value] of Object.entries(props ?? {})) {
    if (value === undefined || value === null || value === false) continue;
    if (key === "class") el.className = String(value);
    else if (key === "style") el.setAttribute("style", String(value));
    else if (key === "dataset") Object.assign(el.dataset, value);
    else if (key.startsWith("on") && typeof value === "function") {
      el.addEventListener(key.slice(2), value as EventListener);
    } else if (value === true) el.setAttribute(key, "");
    else if (key in el && typeof value !== "string") (el as unknown as Record<string, unknown>)[key] = value;
    else el.setAttribute(key, String(value));
  }
  append(el, children);
  return el;
}

export function append(el: Element, children: Child[]) {
  for (const child of children) {
    if (child === null || child === undefined || child === false) continue;
    el.append(child instanceof Node ? child : String(child));
  }
}

export const clear = (el: Element) => el.replaceChildren();

export const sleep = (ms: number) => new Promise<void>((r) => setTimeout(r, ms));

/** Vrátí promise, který se splní po skončení CSS animace (nebo po limitu). */
export function animationEnd(el: Element, timeout = 1500): Promise<void> {
  return new Promise((resolve) => {
    const done = () => {
      clearTimeout(timer);
      el.removeEventListener("animationend", done);
      resolve();
    };
    const timer = setTimeout(done, timeout);
    el.addEventListener("animationend", done, { once: true });
  });
}

export function toast(message: string) {
  document.querySelectorAll(".toast").forEach((t) => t.remove());
  const el = h("div", { class: "toast", role: "status" }, message);
  document.body.append(el);
  setTimeout(() => el.classList.add("toast--out"), 2200);
  setTimeout(() => el.remove(), 2700);
}

export const prefersReducedMotion = () => matchMedia("(prefers-reduced-motion: reduce)").matches;
