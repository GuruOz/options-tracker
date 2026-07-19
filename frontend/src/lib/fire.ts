// Pure FIRE (Financial Independence / Retire Early) maths — no dependencies, so
// sliders re-project instantly with no round-trips.

import type { PlanSettings } from "../api/types";

/** The nest egg needed to draw `targetMonthly` forever at `swrPct` withdrawal. */
export function fireNumber(targetMonthly: number, swrPct: number): number {
  if (swrPct <= 0) return Infinity;
  return (targetMonthly * 12) / (swrPct / 100);
}

/** Month-by-month net worth: compounds monthly + adds monthlySavings. */
export function project(
  netWorth0: number,
  monthlySavings: number,
  annualReturnPct: number,
  months: number,
): number[] {
  const r = annualReturnPct / 100 / 12;
  const out: number[] = [];
  let nw = netWorth0;
  for (let i = 0; i < months; i++) {
    nw = nw * (1 + r) + monthlySavings;
    out.push(nw);
  }
  return out;
}

export interface ScenarioPoint {
  age: number;
  pessimistic: number;
  expected: number;
  optimistic: number;
}

export interface FireResult {
  fireNumber: number;
  progressPct: number;
  monthlySavings: number;
  onTrack: boolean;
  projectedAtRetirement: number | null;
  yearsToFire: number | null; // on the expected scenario
  points: ScenarioPoint[]; // yearly, from now to retirement
}

/** Full FIRE computation from settings + current net worth + savings. */
export function computeFire(
  settings: PlanSettings,
  currentNetWorth: number,
  latestSavings: number | null,
): FireResult {
  const monthlySavings =
    settings.monthly_savings_override ?? latestSavings ?? 0;
  const fireNum = fireNumber(settings.target_monthly_income, settings.swr_pct);
  const yearsToRetire = Math.max(0, settings.retire_age - settings.current_age);
  const months = Math.min(Math.max(yearsToRetire * 12, 12), 720);

  const pess = project(currentNetWorth, monthlySavings, settings.pessimistic_return_pct, months);
  const exp = project(currentNetWorth, monthlySavings, settings.expected_return_pct, months);
  const opt = project(currentNetWorth, monthlySavings, settings.optimistic_return_pct, months);

  const points: ScenarioPoint[] = [];
  points.push({
    age: settings.current_age,
    pessimistic: currentNetWorth,
    expected: currentNetWorth,
    optimistic: currentNetWorth,
  });
  for (let m = 11; m < months; m += 12) {
    points.push({
      age: settings.current_age + Math.round((m + 1) / 12),
      pessimistic: Math.round(pess[m]),
      expected: Math.round(exp[m]),
      optimistic: Math.round(opt[m]),
    });
  }

  const projectedAtRetirement = exp.length ? exp[exp.length - 1] : null;
  const onTrack = projectedAtRetirement != null && projectedAtRetirement >= fireNum;

  let yearsToFire: number | null = null;
  const firstHit = exp.findIndex((v) => v >= fireNum);
  if (firstHit >= 0) yearsToFire = Math.round(((firstHit + 1) / 12) * 10) / 10;

  return {
    fireNumber: fireNum,
    progressPct: fireNum > 0 ? (currentNetWorth / fireNum) * 100 : 0,
    monthlySavings,
    onTrack,
    projectedAtRetirement,
    yearsToFire,
    points,
  };
}
