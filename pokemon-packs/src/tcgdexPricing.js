// Výklad cen z TCGdex (pole `pricing` u karty). Sdílí ho aplikace (src/prices.ts)
// i skript scripts/fetch-prices.mjs, proto je v čistém JavaScriptu (typy v .d.ts).

const num = (v) => (typeof v === "number" && v > 0 ? Math.round(v * 100) / 100 : undefined);

/** Cardmarket trend v EUR a TCGplayer market v USD; chybějící ceny se vynechají. */
export function parseTcgdexPricing(pricing) {
  const cm = pricing?.cardmarket ?? {};
  const tp = pricing?.tcgplayer ?? {};
  const market = (k) => num(tp[k]?.marketPrice) ?? num(tp[k]?.midPrice);
  const out = {
    eur: num(cm.trend) ?? num(cm.avg) ?? num(cm["trend-holo"]) ?? num(cm["avg-holo"]),
    eurReverse: num(cm["trend-holo"]) ?? num(cm["avg-holo"]),
    usd: market("holofoil") ?? market("normal"),
    usdReverse: market("reverse-holofoil") ?? market("reverseHolofoil"),
  };
  return Object.fromEntries(Object.entries(out).filter(([, v]) => v !== undefined));
}
