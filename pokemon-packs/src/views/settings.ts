import { isPersisted, lastBackup, markBackup } from "../storage";
import { exportState, importState, parseBackup, resetState, stateSummary } from "../store";
import { h, toast } from "../ui/dom";

const dateFmt = new Intl.DateTimeFormat("cs-CZ", { dateStyle: "medium" });
const kusu = (n: number) => `${n} ${n === 1 ? "kus" : n >= 2 && n <= 4 ? "kusy" : "kusů"}`;

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
      const input = e.target as HTMLInputElement;
      const file = input.files?.[0];
      // Stejný soubor půjde vybrat znovu.
      input.value = "";
      if (!file) return;
      try {
        const backup = parseBackup(await file.text());
        const next = stateSummary(backup);
        const now = stateSummary();
        const question =
          `Záloha obsahuje ${kusu(next.cards)} karet a ${next.packs} neotevřených balíčků.
` +
          `Nahradit jí současnou sbírku (${kusu(now.cards)} karet, ${now.packs} balíčků)? Současná sbírka se ztratí.`;
        if (now.cards + now.packs > 0 && !confirm(question)) return;
        importState(backup);
        toast("Sbírka obnovena ze zálohy");
        refreshStatus();
      } catch (err) {
        toast(err instanceof Error ? err.message : "Zálohu se nepodařilo načíst");
      }
    },
  });

  const status = h("p", { class: "muted small" });
  const refreshStatus = async () => {
    const at = lastBackup();
    const persisted = await isPersisted();
    status.textContent =
      `Poslední záloha: ${at ? dateFmt.format(at) : "zatím žádná"}. ` +
      (persisted
        ? "Úložiště je trvalé, prohlížeč ho sám nesmaže."
        : "Úložiště není trvalé: při nedostatku místa ho prohlížeč může smazat, proto si sbírku zálohuj.");
  };
  refreshStatus();

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
          {
            class: "btn",
            onclick: () => {
              download(`booster-lab-${new Date().toISOString().slice(0, 10)}.json`, exportState());
              markBackup();
              refreshStatus();
            },
          },
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
      status,
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
          h("a", { href: "https://tcgdex.dev", target: "_blank", rel: "noopener" }, "TCGdex"),
          " (Cardmarket v EUR a TCGplayer v USD), přibalené k aplikaci a obnovované každý den. Sady, které tam chybí, se doplní živě z ",
          h("a", { href: "https://pokemontcg.io", target: "_blank", rel: "noopener" }, "Pokémon TCG API"),
          " (ukládají se na 12 hodin); detail karty zkouší i aktuální cenu z TCGdex.",
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
