// Currency-aware money formatting. Every figure states its currency so a
// USD-base and an SGD-base account can never be confused for one another.
// Codes (USD/SGD) rather than symbols, because "$" is itself ambiguous here.

/** "USD 1,187", "−SGD 158", "+USD 1,500". A null value renders as "—". */
export function fmtCode(
  value: number | null | undefined,
  currency: string | null | undefined = "USD",
  opts: { signed?: boolean } = {},
): string {
  if (value == null) return "—";
  const code = currency || "USD";
  const s = Math.abs(value).toLocaleString(undefined, { maximumFractionDigits: 0 });
  const sign = value < 0 ? "−" : opts.signed ? "+" : "";
  return `${sign}${code} ${s}`;
}

/** The single currency shared by a set of rows, or null when they disagree
 * (or none is recorded). Lets a table print "amounts in USD" only when true. */
export function commonCurrency(
  rows: ReadonlyArray<{ currency?: string | null }>,
): string | null {
  const codes = new Set<string>();
  for (const r of rows) if (r.currency) codes.add(r.currency);
  return codes.size === 1 ? [...codes][0] : null;
}
