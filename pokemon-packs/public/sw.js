// Service worker: aplikace a data karet fungují i offline, obrázky karet
// se po prvním zobrazení ukládají do mezipaměti.

// Při buildu tento řádek nahradí vite.config.ts verzí a seznamem souborů aplikace.
const BUILD = { version: "dev", assets: [] };

const APP_CACHE = `app-${BUILD.version}`;
// Malé obrázky (karty v mřížce, obaly v obchodě) a zvlášť velké (detail karty,
// otevírání), které zabírají mnohem víc místa. Při nedostatku místa prohlížeč
// maže data webu vcelku, i se sbírkou, proto mají velké obrázky malý limit.
const IMG_CACHE = "card-images";
const IMG_LARGE_CACHE = "card-images-large";
const IMG_LIMIT = 2000;
const IMG_LARGE_LIMIT = 150;
const IMAGE_HOSTS = [
  "images.pokemontcg.io",
  "images.scrydex.com",
  "assets.tcgdex.net",
  "tcgplayer-cdn.tcgplayer.com",
  "tcg.pokemon.com",
];
const isLarge = (url) => /_hires\.|\/large$|_in_1000x1000/.test(url);

const scope = new URL(self.registration.scope);
const local = (path) => new URL(path, scope).href;

self.addEventListener("install", (event) => {
  event.waitUntil(
    (async () => {
      const cache = await caches.open(APP_CACHE);
      await cache.addAll([
        local("./"),
        local("manifest.webmanifest"),
        local("icons/icon.svg"),
        local("icons/icon-192.png"),
        ...BUILD.assets.map(local),
      ]);
      // Data všech sad, aby šlo otevírat balíčky i bez připojení.
      const res = await fetch(local("data/sets.json"));
      const sets = await res.clone().json();
      await cache.put(local("data/sets.json"), res);
      await cache.addAll(sets.map((s) => local(`data/${s.id}.json`)));
      await self.skipWaiting();
    })(),
  );
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    (async () => {
      // Mezipaměť předchozí verze (i se starými soubory z buildu) už není potřeba.
      const keys = await caches.keys();
      await Promise.all(keys.filter((k) => k.startsWith("app-") && k !== APP_CACHE).map((k) => caches.delete(k)));
      // Starší verze ukládaly velké obrázky mezi malé.
      const small = await caches.open(IMG_CACHE);
      for (const req of await small.keys()) if (isLarge(req.url)) await small.delete(req);
      await self.clients.claim();
    })(),
  );
});

async function trim(cacheName, limit) {
  const cache = await caches.open(cacheName);
  const keys = await cache.keys();
  for (const req of keys.slice(0, Math.max(0, keys.length - limit))) await cache.delete(req);
}

async function cacheFirst(request, cacheName) {
  const cache = await caches.open(cacheName);
  const hit = await cache.match(request.url);
  if (hit) return hit;
  const res = await fetch(request);
  if (res.ok) await cache.put(request.url, res.clone());
  return res;
}

// Obrázky stahujeme v režimu CORS: neprůhledné (opaque) odpovědi by prohlížeč
// v kvótě úložiště počítal jako několik MB. Když server CORS nepovolí,
// obrázek se jen zobrazí a neuloží.
async function cacheImage(request) {
  const [cacheName, limit] = isLarge(request.url) ? [IMG_LARGE_CACHE, IMG_LARGE_LIMIT] : [IMG_CACHE, IMG_LIMIT];
  const cache = await caches.open(cacheName);
  const hit = await cache.match(request.url);
  if (hit) return hit;
  try {
    const res = await fetch(request.url, { mode: "cors", credentials: "omit" });
    if (res.ok) {
      await cache.put(request.url, res.clone());
      trim(cacheName, limit);
    }
    return res;
  } catch {
    return fetch(request);
  }
}

async function networkFirst(request) {
  const cache = await caches.open(APP_CACHE);
  try {
    const res = await fetch(request);
    if (res.ok) await cache.put(request, res.clone());
    return res;
  } catch {
    return (await cache.match(request)) ?? (await cache.match(local("./")));
  }
}

self.addEventListener("fetch", (event) => {
  const { request } = event;
  if (request.method !== "GET") return;
  const url = new URL(request.url);

  if (IMAGE_HOSTS.includes(url.hostname)) {
    event.respondWith(cacheImage(request));
    return;
  }
  if (url.origin !== scope.origin) return;

  if (request.mode === "navigation" || url.pathname.includes("/data/")) {
    event.respondWith(networkFirst(request));
  } else {
    // Soubory z buildu mají v názvu hash, takže se nemění.
    event.respondWith(cacheFirst(request, APP_CACHE));
  }
});
