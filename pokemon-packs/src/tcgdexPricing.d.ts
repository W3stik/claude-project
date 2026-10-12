export interface ParsedPrice {
  eur?: number;
  eurReverse?: number;
  usd?: number;
  usdReverse?: number;
}

export function parseTcgdexPricing(pricing: unknown): ParsedPrice;
