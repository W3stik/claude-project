import { describe, expect, it } from "vitest";
import { addPrice, formatTotal, type PriceTotal } from "./prices";
import { parseTcgdexPricing } from "./tcgdexPricing.js";

describe("ceny", () => {
  it("součet bez cen v jedné měně tu měnu nezobrazí jako nulu", () => {
    const total: PriceTotal = {};
    addPrice(total, { usd: 1.5 });
    addPrice(total, { usd: 2 }, 2);
    addPrice(total, {});
    expect(total).toEqual({ usd: 5.5 });
    expect(formatTotal(total)).not.toContain("€");
    expect(formatTotal({})).toBe("ceny nejsou dostupné");
  });

  it("výklad cen TCGdex bere reverse holo i ve starším zápisu", () => {
    expect(
      parseTcgdexPricing({
        cardmarket: { trend: 1.234, "trend-holo": 0 },
        tcgplayer: { normal: { marketPrice: 0.5 }, reverseHolofoil: { midPrice: 2 } },
      }),
    ).toEqual({ eur: 1.23, usd: 0.5, usdReverse: 2 });
    expect(parseTcgdexPricing(undefined)).toEqual({});
  });
});
