// Dočasná sonda (2. kolo): náhledy fotek balíčků a rubu karty, opakovaný test
// Pokémon TCG API. Náhledy se vypisují jako base64, aby šly prohlédnout.
import sharp from "sharp";

const ORIGIN = "https://w3stik.github.io";
const PACKS = { sv10: 624683, zsv10pt5: 630434, rsv10pt5: 630699, me1: 644352, me2: 654144, me2pt5: 672434, me3: 672398, me4: 684446, me5: 692944, me55: 696613 };

async function inspect(label, url) {
  const buf = Buffer.from(await (await fetch(url)).arrayBuffer());
  const img = sharp(buf);
  const meta = await img.metadata();
  const { info } = await sharp(buf).trim({ threshold: 20 }).toBuffer({ resolveWithObject: true });
  const { data } = await sharp(buf).resize(4, 4, { fit: "fill" }).raw().toBuffer({ resolveWithObject: true });
  const thumb = await sharp(buf).resize({ width: 150 }).jpeg({ quality: 70 }).toBuffer();
  console.log(`META ${label} ${meta.width}x${meta.height} trim=${info.width}x${info.height}@${-info.trimOffsetLeft},${-info.trimOffsetTop} corner=${[...data.subarray(0, 3)]}`);
  console.log(`THUMB ${label} ${thumb.toString("base64")}`);
}

for (const [set, id] of Object.entries(PACKS)) {
  await inspect(set, `https://tcgplayer-cdn.tcgplayer.com/product/${id}_in_1000x1000.jpg`).catch((e) => console.log("ERR", set, e.message));
}
await inspect("cardback", "https://tcg.pokemon.com/assets/img/global/tcg-card-back-2x.jpg").catch((e) => console.log("ERR back", e.message));

for (let i = 0; i < 3; i++) {
  const res = await fetch("https://api.pokemontcg.io/v2/cards?q=set.id:me1&select=id,cardmarket&pageSize=1", { headers: { Origin: ORIGIN } });
  console.log("pokemontcg.io try", i, res.status, (await res.text()).slice(0, 200).replace(/\s+/g, " "));
  await new Promise((r) => setTimeout(r, 3000));
}
const s = await fetch("https://api.pokemontcg.io/v2/sets/me1", { headers: { Origin: ORIGIN } });
console.log("pokemontcg.io sets/me1", s.status);
