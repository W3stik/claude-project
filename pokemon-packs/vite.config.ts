import { createHash } from "node:crypto";
import { readFile, writeFile } from "node:fs/promises";
import { join } from "node:path";
import { defineConfig, type Plugin } from "vite";

/**
 * Doplní do dist/sw.js seznam souborů z buildu a verzi odvozenou z nich.
 * Service worker se tak změní jen s novým kódem aplikace: nové soubory si
 * předem uloží a mezipaměť se starými smaže (denní nasazení kvůli cenám ho nemění).
 */
function serviceWorkerBuild(): Plugin {
  return {
    name: "booster-lab:sw-build",
    apply: "build",
    async writeBundle(options, bundle) {
      const file = join(options.dir ?? "dist", "sw.js");
      const source = await readFile(file, "utf8");
      const assets = Object.keys(bundle)
        .filter((name) => !name.endsWith(".html"))
        .sort();
      const version = createHash("sha256").update(source).update(assets.join("\n")).digest("hex").slice(0, 10);
      const line = /^const BUILD = .*;$/m;
      if (!line.test(source)) throw new Error("public/sw.js: chybí řádek `const BUILD = …;`");
      await writeFile(file, source.replace(line, `const BUILD = ${JSON.stringify({ version, assets })};`));
    },
  };
}

export default defineConfig({
  // Relativní cesty, aby aplikace fungovala i v podsložce (např. GitHub Pages).
  base: "./",
  build: { target: "es2022" },
  plugins: [serviceWorkerBuild()],
});
