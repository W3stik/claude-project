// Dočasná sonda: ověří zdroje obrázků balíčků, rubu karty a cen z běžné sítě.
const ORIGIN = "https://w3stik.github.io";
const UA = { "User-Agent": "BoosterLab/0.1 (fan pack simulator)" };
const tcgcsv = async (path) => (await (await fetch(`https://tcgcsv.com/tcgplayer/3/${path}`, { headers: UA })).json()).results;
const SETS = ["Destined Rivals", "Black Bolt", "White Flare", "Mega Evolution", "Phantasmal Flames", "Ascended Heroes", "Perfect Order", "Chaos Rising", "Pitch Black", "30th Celebration"];

async function head(url, extra = {}) {
  try {
    const res = await fetch(url, { headers: { Origin: ORIGIN, ...extra }, redirect: "follow" });
    const buf = await res.arrayBuffer();
    return `${res.status} ${res.headers.get("content-type")} acao=${res.headers.get("access-control-allow-origin")} bytes=${buf.byteLength} final=${res.url}`;
  } catch (e) {
    return `ERR ${e.message}`;
  }
}

console.log("== groups");
const groups = await tcgcsv("groups");
for (const name of SETS) {
  const gs = groups.filter((g) => g.name.toLowerCase().includes(name.toLowerCase()));
  for (const g of gs) {
    console.log(`GROUP ${g.groupId} | ${g.name} | ${g.abbreviation} | ${g.publishedOn}`);
    const prods = await tcgcsv(`${g.groupId}/products`);
    for (const p of prods.filter((p) => /booster pack|pack art/i.test(p.name) || /booster/i.test(p.name) && !p.extendedData?.some((e) => e.name === "Number"))) {
      console.log(`  PROD ${p.productId} | ${p.name} | ${p.imageUrl}`);
    }
  }
}

console.log("== image checks");
const sample = 624683;
for (const suffix of ["_200w.jpg", "_400w.jpg", "_in_1000x1000.jpg", "_in_800x800.jpg"]) {
  console.log(suffix, await head(`https://tcgplayer-cdn.tcgplayer.com/product/${sample}${suffix}`));
  console.log(suffix, "referer", await head(`https://tcgplayer-cdn.tcgplayer.com/product/${sample}${suffix}`, { Referer: ORIGIN + "/" }));
}
console.log("cardback", await head("https://tcg.pokemon.com/assets/img/global/tcg-card-back-2x.jpg", { Referer: ORIGIN + "/" }));
console.log("cardback1x", await head("https://tcg.pokemon.com/assets/img/global/tcg-card-back.jpg", { Referer: ORIGIN + "/" }));
console.log("scrydex", await head("https://images.scrydex.com/pokemon/me5-1/small"));
console.log("scrydex logo", await head("https://images.scrydex.com/pokemon/me5-logo/logo"));
console.log("ptcg img", await head("https://images.pokemontcg.io/sv10/1.png"));

console.log("== pokemontcg.io");
try {
  const res = await fetch("https://api.pokemontcg.io/v2/cards?q=set.id:me1&select=id,tcgplayer,cardmarket&pageSize=2", { headers: { Origin: ORIGIN } });
  console.log(res.status, "acao", res.headers.get("access-control-allow-origin"));
  console.log((await res.text()).slice(0, 1500));
  const res2 = await fetch("https://api.pokemontcg.io/v2/cards?q=set.id:me5&select=id,tcgplayer,cardmarket&pageSize=250", { headers: { Origin: ORIGIN } });
  const b2 = await res2.json();
  console.log("me5 count", b2.totalCount, "withCM", b2.data?.filter((c) => c.cardmarket).length, "withTP", b2.data?.filter((c) => c.tcgplayer).length);
  const res3 = await fetch("https://api.pokemontcg.io/v2/cards?q=set.id:me55c&select=id,tcgplayer,cardmarket&pageSize=250", { headers: { Origin: ORIGIN } });
  const b3 = await res3.json();
  console.log("me55c count", b3.totalCount, "withCM", b3.data?.filter((c) => c.cardmarket).length, "withTP", b3.data?.filter((c) => c.tcgplayer).length);
} catch (e) {
  console.log("ERR", e.message);
}

console.log("== tcgdex");
try {
  const res = await fetch("https://api.tcgdex.net/v2/en/sets", { headers: { Origin: ORIGIN } });
  console.log(res.status, "acao", res.headers.get("access-control-allow-origin"));
  const sets = await res.json();
  for (const name of SETS) console.log("  ", name, JSON.stringify(sets.filter((s) => s.name.toLowerCase().includes(name.toLowerCase())).map((s) => [s.id, s.name])));
  const s = await (await fetch("https://api.tcgdex.net/v2/en/sets/me01")).json();
  console.log("me01 keys", Object.keys(s), "boosters", JSON.stringify(s.boosters)?.slice(0, 800));
  const first = s.cards?.[0];
  console.log("first card", JSON.stringify(first));
  if (first) console.log("card pricing", JSON.stringify((await (await fetch(`https://api.tcgdex.net/v2/en/cards/${first.id}`)).json()).pricing)?.slice(0, 1200));
} catch (e) {
  console.log("ERR", e.message);
}
