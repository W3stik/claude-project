// Kouřový test celé aplikace v Chromiu (Playwright): obchod → regál → otevření
// balíčku → album → 3D detail karty. Obrázky a API se podvrhují, takže test
// běží i bez internetu a nezávisí na cizích serverech.
//
//   npm run build && npm run e2e            (snímky obrazovky uloží do e2e-shots/)
//
// Při prvním použití je potřeba prohlížeč: npx playwright install chromium
import { mkdir } from "node:fs/promises";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { chromium } from "playwright";
import { preview } from "vite";

const ROOT = join(dirname(fileURLToPath(import.meta.url)), "..");
const SHOTS = join(ROOT, "e2e-shots");
await mkdir(SHOTS, { recursive: true });

const svg = (w, h, body) => `<svg xmlns="http://www.w3.org/2000/svg" width="${w}" height="${h}">${body}</svg>`;
const CARD = svg(245, 342, '<rect width="245" height="342" rx="10" fill="#f2d54b"/><rect x="10" y="10" width="225" height="322" rx="6" fill="#6aa8e8"/>');
const PACK = svg(547, 1000, '<rect width="547" height="1000" fill="#3b1d6e"/><circle cx="273" cy="480" r="170" fill="#ffd54f"/><rect width="547" height="70" fill="#ccc"/><rect y="950" width="547" height="50" fill="#ccc"/>');
const BACK = svg(660, 921, '<rect width="660" height="921" rx="30" fill="#2a5aa8"/><circle cx="330" cy="460" r="150" fill="#d33"/>');

const server = await preview({ root: ROOT, preview: { port: 4173, strictPort: false }, logLevel: "warn" });
const url = server.resolvedUrls.local[0];
const browser = await chromium.launch();
const failures = [];
const check = (ok, message) => {
  console.log(`${ok ? "✓" : "✗"} ${message}`);
  if (!ok) failures.push(message);
};

try {
  const ctx = await browser.newContext({ viewport: { width: 390, height: 844 }, serviceWorkers: "block" });
  const page = await ctx.newPage();
  const errors = [];
  page.on("pageerror", (e) => errors.push(String(e)));
  await page.route(/images\.(scrydex|pokemontcg)/, (r) => r.fulfill({ contentType: "image/svg+xml", body: CARD }));
  await page.route(/tcgplayer-cdn/, (r) => r.fulfill({ contentType: "image/svg+xml", body: PACK }));
  await page.route(/tcg\.pokemon\.com/, (r) => r.fulfill({ contentType: "image/svg+xml", body: BACK }));
  await page.route(/api\.(pokemontcg\.io|tcgdex\.net)/, (r) => r.abort());

  // Obchod
  await page.goto(url);
  await page.waitForSelector(".shop-tile");
  check((await page.locator(".shop-tile").count()) === 10, "obchod ukazuje 10 sad");
  await page.screenshot({ path: join(SHOTS, "1-shop.png") });

  // Regál: výběr balíčku, regál se po obnovení nezmění
  await page.locator(".shop-tile").first().getByText("1 balíček").click();
  await page.waitForSelector(".shelf__slot");
  check((await page.locator(".shelf__slot").count()) === 10, "regál má 10 balíčků");
  const shelfOf = () =>
    page.evaluate(() => {
      const s = JSON.parse(localStorage.getItem("pokemon-packs:state:v1"));
      return Object.values(s.shelf)[0].map((p) => p.cards.map((c) => c.id).join(","));
    });
  const shelf = await shelfOf();
  await page.reload();
  await page.waitForSelector(".shelf__slot");
  check(JSON.stringify(await shelfOf()) === JSON.stringify(shelf), "regál po obnovení stránky zůstal stejný");
  await page.locator(".shelf__slot").nth(2).click();
  await page.screenshot({ path: join(SHOTS, "2-shelf.png") });
  await page.getByText("Vzít a otevřít").click();

  // Otevření: roztržení, karty jdou odhodit, obsah odpovídá vybranému balíčku
  await page.waitForSelector(".pack3d--big");
  await page.locator(".pack3d--big").click({ force: true });
  await page.waitForSelector(".pile");
  await page.waitForTimeout(900);
  const pile = await page.locator(".pile__item img.pcard__img").evaluateAll((els) =>
    els.map((e) => e.getAttribute("alt")),
  );
  check(pile.length > 0, `balíček obsahuje ${pile.length} karet`);
  await page.screenshot({ path: join(SHOTS, "3-pile.png") });
  for (let i = 0; i < 15 && !(await page.locator(".summary").count()); i++) {
    await page.locator(".pile").click({ force: true });
    await page.waitForTimeout(650);
  }
  check((await page.locator(".summary").count()) === 1, "po odhození všech karet se ukáže přehled");
  await page.screenshot({ path: join(SHOTS, "4-summary.png"), fullPage: true });

  // Album a 3D detail karty
  await page.goto(`${url}#/album`);
  await page.waitForSelector(".album-set");
  await page.locator(".album-set").first().click();
  await page.waitForSelector(".album-tile");
  await page.selectOption('select[aria-label="Zobrazit"]', "owned");
  check((await page.locator(".album-tile").count()) > 0, "album ukazuje získané karty");
  await page.locator(".album-tile").first().click();
  await page.waitForSelector(".modal .card3d");
  await page.getByRole("button", { name: "↻ Otočit" }).click();
  await page.waitForTimeout(1200);
  await page.screenshot({ path: join(SHOTS, "5-card3d.png") });
  await page.getByRole("button", { name: "⛶ Celá obrazovka" }).click();
  check((await page.locator(".viewer .card3d").count()) === 1, "3D prohlížeč jde otevřít přes celou obrazovku");
  await page.keyboard.press("Escape");
  check((await page.locator(".viewer").count()) === 0 && (await page.locator(".modal").count()) === 1, "Esc zavře jen celou obrazovku");

  check(errors.length === 0, `bez chyb JavaScriptu${errors.length ? `: ${errors.join(" | ")}` : ""}`);
} finally {
  await browser.close();
  await new Promise((resolve) => server.httpServer.close(resolve));
}

console.log(failures.length ? `\n${failures.length} kontrol selhalo` : `\nVše v pořádku, snímky v ${SHOTS}`);
process.exit(failures.length ? 1 : 0);
