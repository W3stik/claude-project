import { defineConfig } from "vite";

export default defineConfig({
  // Relativní cesty, aby aplikace fungovala i v podsložce (např. GitHub Pages).
  base: "./",
  build: { target: "es2022" },
});
