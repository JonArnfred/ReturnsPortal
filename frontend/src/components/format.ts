const integer = new Intl.NumberFormat("en-US", { maximumFractionDigits: 0 });

export function formatNumber(value: number | null | undefined, digits = 0): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "-";
  if (digits === 0) return integer.format(value);
  return new Intl.NumberFormat("en-US", { minimumFractionDigits: digits, maximumFractionDigits: digits }).format(value);
}

/** API decimals arrive as strings; this turns them into numbers for display, keeping null as null. */
export function toNumber(value: string | number | null | undefined): number | null {
  return value === null || value === undefined ? null : Number(value);
}

/** Share quantities: up to four decimals, no trailing zeros. */
export function formatQuantity(value: number | null | undefined): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "-";
  return new Intl.NumberFormat("en-US", { maximumFractionDigits: 4 }).format(value);
}

const rate = new Intl.NumberFormat("en-US", { maximumSignificantDigits: 6 });

/** FX rates: six significant digits, so 7.47480 and 0.0413142 both keep their precision. */
export function formatRate(value: number | null | undefined): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "-";
  return rate.format(value);
}

export function formatPct(value: number | null | undefined, digits = 2): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "-";
  return (value * 100).toFixed(digits);
}

export function signColor(value: number | null | undefined): string | undefined {
  if (value === null || value === undefined) return undefined;
  if (value > 0) return "success.main";
  if (value < 0) return "error.main";
  return undefined;
}

/** A column label with its currency, e.g. "NAV (EUR)"; just the label until the currency is known. */
export function withCurrency(label: string, currency: string | null | undefined): string {
  return currency ? `${label} (${currency})` : label;
}
