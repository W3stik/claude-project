import { exportState, importState, resetState } from "../store";
import { h, toast } from "../ui/dom";

function download(name: string, text: string) {
  const url = URL.createObjectURL(new Blob([text], { type: "application/json" }));
  const a = h("a", { href: url, download: name });
  document.body.append(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

export function renderSettings(root: HTMLElement) {
  const fileInput = h("input", {
    type: "file",
    accept: "application/json,.json",
    class: "hidden",
    onchange: async (e: Event) => {
      const file = (e.target as HTMLInputElement).files?.[0];
      if (!file) return;
      try {
        importState(await file.text());
        toast("Sbírka obnovena ze zálohy");
      } catch (err) {
        toast(err instanceof Error ? err.message : "Zálohu se nepodařilo načíst");
      }
    },
  });

  root.append(
    h("section", { class: "view-head" }, h("h1", null, "Více")),
    h(
      "section",
      { class: "panel" },
      h("h2", null, "Záloha sbírky"),
      h(
        "p",
        { class: "muted" },
        "Sbírka se ukládá jen v tomto prohlížeči. Zálohou ji přeneseš do jiného zařízení (např. z počítače do telefonu).",
      ),
      h(
        "div",
        { class: "row" },
        h(
          "button",
          { class: "btn", onclick: () => download(`booster-lab-${new Date().toISOString().slice(0, 10)}.json`, exportState()) },
          "Stáhnout zálohu",
        ),
        h("button", { class: "btn", onclick: () => fileInput.click() }, "Nahrát zálohu"),
        fileInput,
        h(
          "button",
          {
            class: "btn btn--danger",
            onclick: () => {
              if (confirm("Opravdu smazat celou sbírku a všechny neotevřené balíčky?")) {
                resetState();
                toast("Sbírka smazána");
              }
            },
          },
          "Smazat sbírku",
        ),
      ),
    ),
    h(
      "section",
      { class: "panel" },
      h("h2", null, "Odkud jsou data"),
      h(
        "ul",
        { class: "plain" },
        h(
          "li",
          null,
          "Karty a sady: ",
          h("a", { href: "https://github.com/PokemonTCG/pokemon-tcg-data", target: "_blank", rel: "noopener" }, "PokemonTCG/pokemon-tcg-data"),
          " (stejná data jako Pokémon TCG API).",
        ),
        h(
          "li",
          null,
          "Ceny: ",
          h("a", { href: "https://pokemontcg.io", target: "_blank", rel: "noopener" }, "Pokémon TCG API"),
          " (Cardmarket v EUR a TCGplayer v USD), záložně ",
          h("a", { href: "https://tcgdex.dev", target: "_blank", rel: "noopener" }, "TCGdex"),
          ". Ukládají se na 12 hodin.",
        ),
        h(
          "li",
          null,
          "Šance na tah: měření TCGplayer a komunitní statistiky. Přesné zdroje najdeš u každé sady v obchodě pod „Šance a zdroje“.",
        ),
      ),
    ),
    h(
      "section",
      { class: "panel" },
      h("h2", null, "Upozornění"),
      h(
        "p",
        { class: "muted" },
        "Neoficiální fanouškovský projekt pro soukromé použití, bez reklam a bez prodeje. Pokémon, názvy karet a ilustrace patří společnostem Nintendo, Creatures, GAME FREAK a The Pokémon Company. Projekt s nimi nijak nesouvisí.",
      ),
    ),
  );
}
