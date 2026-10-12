import { packProfile, packSize } from "../odds";
import type { SetInfo } from "../types";
import { h } from "./dom";
import { enableTilt } from "./holo";

/**
 * Produkty „Booster Pack“ v katalogu TCGplayer (productId). Fotky obalů se
 * načítají z jejich CDN; ID jsou z exportu katalogu na tcgcsv.com.
 */
export const PACK_PRODUCTS: Record<string, number> = {
  sv10: 624683,
  zsv10pt5: 630434,
  rsv10pt5: 630699,
  me1: 644352,
  me2: 654144,
  me2pt5: 672434,
  me3: 672398,
  me4: 684446,
  me5: 692944,
  me55: 696613,
};

export function packArtUrl(setId: string, large = false): string | null {
  const id = PACK_PRODUCTS[setId];
  if (!id) return null;
  return `https://tcgplayer-cdn.tcgplayer.com/product/${id}_${large ? "in_1000x1000" : "400w"}.jpg`;
}

/** Náhradní potisk, když fotka obalu chybí nebo se nenačte. */
function fallbackArt(set: SetInfo): HTMLElement {
  return h(
    "div",
    { class: "pack3d__fallback" },
    h("div", { class: "pack__series" }, set.series),
    h("img", { class: "pack__logo", src: set.logo, alt: "", draggable: "false" }),
    h("div", { class: "pack__label" }, `Booster Pack · ${packSize(packProfile(set.id))} karet`),
  );
}

/**
 * 3D balíček: přední a zadní strana, boky a odtrhávací horní pruh.
 * Obě části (pruh i zbytek) kreslí stejný obrázek, jen každá jeho jiný výřez,
 * takže při roztržení se obal opravdu rozdělí.
 */
export function packEl(set: SetInfo, opts: { large?: boolean; tilt?: boolean; hint?: number } = {}): HTMLElement {
  const [c1, c2] = packProfile(set.id).colors;
  const art = packArtUrl(set.id, opts.large);
  // Zadní strana: rozmazaná a ztmavená fotka (skutečný rub obalu nemáme), ať text nejde přečíst.
  const face = (side: "front" | "back") =>
    h(
      "div",
      { class: `pack3d__face pack3d__face--${side}` },
      side === "front" ? fallbackArt(set) : h("div", { class: "pack3d__backart" }),
    );
  const mainFront = face("front");
  if (opts.hint) mainFront.append(twinkle(opts.hint));

  const pack = h(
    "div",
    {
      class: `pack3d${art ? "" : " pack3d--noart"}`,
      style: `--c1: ${c1}; --c2: ${c2};${art ? ` --art: url("${art}");` : ""}`,
      role: "img",
      "aria-label": `Balíček ${set.name}`,
    },
    h(
      "div",
      { class: "pack3d__tilt" },
      h(
        "div",
        { class: "pack3d__body" },
        h("div", { class: "pack3d__piece pack3d__piece--top" }, face("front"), face("back")),
        h(
          "div",
          { class: "pack3d__piece pack3d__piece--main" },
          mainFront,
          face("back"),
          h("div", { class: "pack3d__side pack3d__side--left" }),
          h("div", { class: "pack3d__side pack3d__side--right" }),
        ),
      ),
    ),
    h("div", { class: "pack3d__shadow" }),
  );

  if (art) {
    // Poměr stran podle skutečné fotky; při chybě zůstane náhradní potisk.
    const img = new Image();
    img.onload = () => pack.style.setProperty("--ratio", String(img.naturalWidth / img.naturalHeight));
    img.onerror = () => pack.classList.add("pack3d--noart");
    img.src = art;
  }
  if (opts.tilt) enableTilt(pack);
  return pack;
}

/**
 * Tajný náznak vzácné karty: drobná jiskřička, která jednou za čas
 * problikne na náhodném místě obalu. Čím vzácnější karta, tím častěji a barevněji.
 */
function twinkle(level: number): HTMLElement {
  const period = [0, 7.5, 5.5, 3.8][level];
  const x = 18 + Math.random() * 64;
  const y = 22 + Math.random() * 60;
  return h("div", {
    class: `pack3d__twinkle pack3d__twinkle--${level}`,
    style: `left: ${x}%; top: ${y}%; animation-duration: ${period}s; animation-delay: ${-Math.random() * period}s`,
  });
}

const dateFmt = new Intl.DateTimeFormat("cs-CZ", { day: "numeric", month: "long", year: "numeric" });
export const formatDate = (iso: string) => dateFmt.format(new Date(`${iso}T12:00:00`));
