// Black–Scholes option pricing + helpers, client-side so the profit grid and
// payoff curve recompute instantly as the user drags the IV / price-range
// controls (no server round-trip). Mirrors backend/app/analytics/decay.py.

const RISK_FREE = 0.04;

// Abramowitz & Stegun 7.1.26 — max error ~1.5e-7, plenty for a pricing grid.
function erf(x: number): number {
  const t = 1 / (1 + 0.3275911 * Math.abs(x));
  const y =
    1 -
    ((((1.061405429 * t - 1.453152027) * t + 1.421413741) * t - 0.284496736) * t + 0.254829592) *
      t *
      Math.exp(-x * x);
  return x >= 0 ? y : -y;
}

export function normCdf(x: number): number {
  return 0.5 * (1 + erf(x / Math.SQRT2));
}

export function intrinsic(isCall: boolean, S: number, K: number): number {
  return Math.max(0, isCall ? S - K : K - S);
}

// IBKR's IV field is a percent (23.0 == 23%); a value > 3 can only be a percentage.
export function normalizeIv(iv: number): number {
  return iv > 3 ? iv / 100 : iv;
}

export function bsPrice(
  isCall: boolean,
  S: number,
  K: number,
  tYears: number,
  sigma: number,
  r: number = RISK_FREE,
): number {
  if (tYears <= 0 || sigma <= 0 || S <= 0 || K <= 0) return intrinsic(isCall, S, K);
  const volT = sigma * Math.sqrt(tYears);
  const d1 = (Math.log(S / K) + (r + 0.5 * sigma * sigma) * tYears) / volT;
  const d2 = d1 - volT;
  const disc = Math.exp(-r * tYears);
  return isCall
    ? S * normCdf(d1) - K * disc * normCdf(d2)
    : K * disc * normCdf(-d2) - S * normCdf(-d1);
}

/**
 * Solve the implied volatility that reprices `price` via bisection. Returns null
 * when there's no time value to imply from (price at/below intrinsic, e.g. a stale
 * or crossed quote) so callers can fall back to a quoted IV. Anchoring the grid to
 * the implied vol makes the "today @ spot" cell reproduce the live mark, so the
 * current-spot/current-date cell matches the position's real unrealized P&L.
 */
export function impliedVol(
  isCall: boolean,
  S: number,
  K: number,
  tYears: number,
  price: number,
  r: number = RISK_FREE,
): number | null {
  if (tYears <= 0 || S <= 0 || K <= 0) return null;
  if (price <= intrinsic(isCall, S, K) + 1e-6) return null;
  let lo = 1e-4;
  let hi = 5; // 500% vol ceiling
  if (bsPrice(isCall, S, K, tYears, hi, r) < price) return null; // unreachable
  for (let i = 0; i < 64; i++) {
    const mid = (lo + hi) / 2;
    if (bsPrice(isCall, S, K, tYears, mid, r) > price) hi = mid;
    else lo = mid;
  }
  return (lo + hi) / 2;
}
