import { packProfile, packSize } from "../odds";
import type { SetInfo } from "../types";
import { h } from "./dom";

/** Obal balíčku poskládaný z barev sady a jejího oficiálního loga. */
export function packEl(set: SetInfo): HTMLElement {
  const profile = packProfile(set.id);
  const [c1, c2] = profile.colors;
  return h(
    "div",
    { class: "pack", style: `--c1: ${c1}; --c2: ${c2}` },
    h("div", { class: "pack__top" }, h("div", { class: "pack__crimp" })),
    h(
      "div",
      { class: "pack__main" },
      h("div", { class: "pack__series" }, set.series),
      h("img", { class: "pack__logo", src: set.logo, alt: set.name, draggable: "false" }),
      h("div", { class: "pack__label" }, `Booster Pack · ${packSize(profile)} karet`),
      h("div", { class: "pack__crimp pack__crimp--bottom" }),
    ),
  );
}

const dateFmt = new Intl.DateTimeFormat("cs-CZ", { day: "numeric", month: "long", year: "numeric" });
export const formatDate = (iso: string) => dateFmt.format(new Date(`${iso}T12:00:00`));
