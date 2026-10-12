import "./styles.css";
import { subscribe, unopenedTotal } from "./store";
import { clear, h } from "./ui/dom";
import { renderAlbum } from "./views/album";
import { renderOpen } from "./views/open";
import { renderPick } from "./views/pick";
import { renderSettings } from "./views/settings";
import { renderShop } from "./views/shop";

const view = document.getElementById("view")!;
const packBadge = document.getElementById("pack-badge")!;

const routes: Record<string, (root: HTMLElement, arg?: string) => void | Promise<void>> = {
  shop: renderShop,
  open: renderOpen,
  album: renderAlbum,
  more: renderSettings,
  pick: renderPick,
};

/** Podstránky, které v navigaci patří pod jinou záložku. */
const TAB_OF: Record<string, string> = { pick: "shop" };

let renderId = 0;

async function route() {
  const [name = "shop", arg] = location.hash.replace(/^#\/?/, "").split("/");
  const render = routes[name] ?? renderShop;
  const id = ++renderId;

  document.querySelectorAll<HTMLAnchorElement>(".tabbar a").forEach((a) => {
    a.classList.toggle("active", a.dataset.route === (routes[name] ? (TAB_OF[name] ?? name) : "shop"));
  });

  // Každá obrazovka se kreslí do nového kontejneru, aby pomalé načítání
  // předchozí obrazovky nepřepsalo tu aktuální.
  const root = h("div", { class: "view-root" });
  clear(view);
  view.append(root);
  window.scrollTo({ top: 0 });
  try {
    await render(root, arg);
  } catch (err) {
    if (id !== renderId) return;
    root.replaceChildren(
      h(
        "div",
        { class: "empty" },
        h("p", null, "Něco se nepovedlo načíst."),
        h("p", { class: "muted small" }, err instanceof Error ? err.message : String(err)),
        h("button", { class: "btn", onclick: () => route() }, "Zkusit znovu"),
      ),
    );
  }
}

function updateBadge() {
  const n = unopenedTotal();
  packBadge.textContent = n > 99 ? "99+" : String(n);
  packBadge.classList.toggle("hidden", n === 0);
}

window.addEventListener("hashchange", route);
subscribe(updateBadge);
updateBadge();
route();

if ("serviceWorker" in navigator && import.meta.env.PROD) {
  window.addEventListener("load", () => {
    navigator.serviceWorker.register(`${import.meta.env.BASE_URL}sw.js`).catch(() => {
      // Bez service workeru aplikace funguje dál, jen ne offline.
    });
  });
}
