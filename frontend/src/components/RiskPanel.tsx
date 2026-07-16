import { useQuery } from "@tanstack/react-query";
import { getJSON, withAccount } from "../api/client";
import type { Risk } from "../api/types";
import { useAccount } from "../hooks/useAccount";

const money = (v: number | null | undefined, signed = false) => {
  if (v == null) return "—";
  const s = Math.abs(v).toLocaleString(undefined, { maximumFractionDigits: 0 });
  if (v < 0) return `−$${s}`;
  return signed ? `+$${s}` : `$${s}`;
};
const pct = (v: number | null | undefined, d = 1) =>
  v == null ? "—" : `${(v * 100).toFixed(d)}%`;

/** Tiny inline equity-curve sparkline (no chart lib needed). */
function Sparkline({ points }: { points: number[] }) {
  if (points.length < 2) return null;
  const w = 260;
  const h = 44;
  const pad = 3;
  const min = Math.min(...points);
  const max = Math.max(...points);
  const range = max - min || 1;
  const dx = (w - pad * 2) / (points.length - 1);
  const y = (p: number) => h - pad - ((p - min) / range) * (h - pad * 2);
  const path = points
    .map((p, i) => `${i === 0 ? "M" : "L"} ${(pad + i * dx).toFixed(1)} ${y(p).toFixed(1)}`)
    .join(" ");
  const up = points[points.length - 1] >= points[0];
  const stroke = up ? "#10b981" : "#ef4444";
  return (
    <svg viewBox={`0 0 ${w} ${h}`} className="h-11 w-full" preserveAspectRatio="none">
      <path d={path} fill="none" stroke={stroke} strokeWidth={1.5} vectorEffect="non-scaling-stroke" />
    </svg>
  );
}

function Stat({
  label,
  value,
  sub,
  tone = "default",
  title,
}: {
  label: string;
  value: string;
  sub?: string;
  tone?: "default" | "good" | "bad" | "warn";
  title?: string;
}) {
  const toneClass =
    tone === "good"
      ? "text-emerald-600 dark:text-emerald-400"
      : tone === "bad"
      ? "text-red-600 dark:text-red-400"
      : tone === "warn"
      ? "text-amber-600 dark:text-amber-400"
      : "text-slate-800 dark:text-slate-100";
  return (
    <div className="rounded-lg border border-slate-200 p-4 dark:border-slate-700 dark:bg-slate-800" title={title}>
      <div className="text-xs uppercase tracking-wide text-slate-400 dark:text-slate-500">{label}</div>
      <div className={`mt-1 text-2xl font-bold tabular-nums ${toneClass}`}>{value}</div>
      {sub && <div className="mt-0.5 text-xs text-slate-500 dark:text-slate-400">{sub}</div>}
    </div>
  );
}

export function RiskPanel() {
  const { selected } = useAccount();
  const { data } = useQuery({
    queryKey: ["risk", selected],
    queryFn: () => getJSON<Risk | null>(withAccount("/api/risk", selected)),
  });
  if (!data) return null;

  const perAccount = data.per_account ?? [];
  const isCombined = perAccount.length > 0;

  const movePct = `${(data.scenario_move * 100).toFixed(0)}%`;
  const scenarioTone = (data.scenario_pnl ?? 0) < 0 ? "bad" : "good";

  const cov = data.assignment.coverage_ratio;
  const covTone = cov == null ? "default" : cov >= 1 ? "good" : "warn";
  const covBar = cov == null ? 0 : Math.min(cov, 2) / 2 * 100; // bar maxes at 200%

  // Combined mode returns no summed curve: each account's snapshots land on
  // their own timestamps, so the accounts' curves are shown side by side below.
  const equity = data.equity_curve
    .map((e) => e.net_liquidation)
    .filter((v): v is number => v != null);
  const equityFirst = equity[0];
  const equityLast = equity[equity.length - 1];
  const equityChange =
    equityFirst != null && equityLast != null ? equityLast - equityFirst : null;

  const top = data.positions.slice(0, 5);

  return (
    <section className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm dark:border-slate-700 dark:bg-slate-900">
      <div className="mb-3 flex items-baseline justify-between">
        <h2 className="text-base font-semibold text-slate-800 dark:text-slate-100">
          Portfolio risk{isCombined ? " — all accounts" : ""}
        </h2>
        <span className="text-xs text-slate-400 dark:text-slate-500">linear estimate — not advice</span>
      </div>

      {data.currency_mismatch && (
        <p className="mb-3 text-xs text-amber-600 dark:text-amber-400">
          Positions are held in a different currency than the account
          {data.exposure_currency ? ` (${data.exposure_currency} vs. account currency)` : ""} —
          scenario P&amp;L % and assignment coverage aren't shown to avoid dividing mismatched currencies.
        </p>
      )}

      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 xl:grid-cols-4">
        <Stat
          label="Net liquidation"
          value={money(data.net_liquidation)}
          sub={equityChange != null ? `${equityChange >= 0 ? "▲" : "▼"} ${money(equityChange, true)} over window` : undefined}
          title="Current account net liquidation value."
        />
        <Stat
          label={`${data.index_symbol ?? "Index"} ${movePct} scenario`}
          value={money(data.scenario_pnl)}
          sub={`${pct(data.scenario_pnl_pct)} of net liq · β-weighted Δ ${money(data.beta_weighted_delta_dollars)}`}
          tone={scenarioTone}
          title={`Estimated P&L if ${data.index_symbol ?? "the index"} moves ${movePct}, using beta-weighted dollar delta. First-order linear estimate.`}
        />
        <Stat
          label="Assignment coverage"
          value={cov == null ? "—" : `${cov.toFixed(2)}×`}
          sub={
            data.assignment.short_put_count === 0
              ? "No short puts"
              : `${money(data.assignment.cash)} cash / ${money(data.assignment.total_obligation)} obligation${
                  isCombined ? " · pooled" : ""
                }`
          }
          tone={covTone}
          title={
            isCombined
              ? "Cash on hand vs. total cost if every short put were assigned, pooled across accounts. Approximate: cash in one account can't actually cover the other's assignment."
              : "Cash on hand vs. total cost if every short put were assigned (strike × 100 × contracts)."
          }
        />
        <div className="rounded-lg border border-slate-200 p-4 dark:border-slate-700 dark:bg-slate-800">
          <div className="text-xs uppercase tracking-wide text-slate-400 dark:text-slate-500">Equity curve</div>
          {isCombined ? (
            <div className="mt-1 space-y-1">
              {perAccount.map((a) => {
                const pts = a.equity_curve
                  .map((e) => e.net_liquidation)
                  .filter((v): v is number => v != null);
                return (
                  <div key={a.account_id} className="flex items-center gap-2">
                    <span className="w-16 shrink-0 truncate text-[10px] text-slate-400 dark:text-slate-500">
                      {a.account_label}
                    </span>
                    {pts.length >= 2 ? (
                      <Sparkline points={pts} />
                    ) : (
                      <span className="text-[10px] text-slate-400">not enough history</span>
                    )}
                  </div>
                );
              })}
            </div>
          ) : equity.length >= 2 ? (
            <div className="mt-1">
              <Sparkline points={equity} />
            </div>
          ) : (
            <div className="mt-3 text-xs text-slate-500 dark:text-slate-400">Not enough history yet.</div>
          )}
        </div>
      </div>

      {/* Coverage bar */}
      {cov != null && (
        <div className="mt-4">
          <div className="mb-1 flex items-center justify-between text-xs text-slate-500 dark:text-slate-400">
            <span>Assignment coverage</span>
            <span className="tabular-nums">{cov.toFixed(2)}× {cov >= 1 ? "(covered)" : "(under-covered)"}</span>
          </div>
          <div className="h-2 w-full rounded-full bg-slate-100 dark:bg-slate-700">
            <div
              className={`h-2 rounded-full ${cov >= 1 ? "bg-emerald-500" : "bg-amber-500"}`}
              style={{ width: `${covBar}%` }}
            />
          </div>
        </div>
      )}

      {/* Top scenario contributors */}
      {top.length > 0 && (
        <div className="mt-4">
          <div className="mb-1 text-xs uppercase tracking-wide text-slate-400 dark:text-slate-500">
            Largest contributors to {movePct} scenario
          </div>
          <table className="w-full text-sm">
            <thead>
              <tr className="text-left text-xs uppercase tracking-wide text-slate-400 dark:text-slate-500 border-b border-slate-100 dark:border-slate-700">
                <th className="py-1.5 pr-3" title="Underlying (and strike/right for options).">Position</th>
                <th className="pr-3 text-right" title="Beta used to weight this name to the index.">β</th>
                <th className="pr-3 text-right" title="Beta-weighted dollar delta — index-equivalent exposure.">β-wtd Δ$</th>
                <th className="text-right" title={`Estimated P&L contribution on the ${movePct} index move.`}>Scenario P&amp;L</th>
              </tr>
            </thead>
            <tbody>
              {top.map((c, i) => (
                <tr key={`${c.symbol}-${i}`} className="border-t border-slate-100 dark:border-slate-700">
                  <td className="py-1.5 pr-3 font-medium text-slate-700 dark:text-slate-200">
                    {c.symbol}
                    {c.right ? ` ${c.strike ?? ""}${c.right}` : ""}
                  </td>
                  <td className="pr-3 text-right tabular-nums text-slate-500 dark:text-slate-400" title="Beta used">
                    β {c.beta?.toFixed(2) ?? "—"}
                  </td>
                  <td className="pr-3 text-right tabular-nums text-slate-500 dark:text-slate-400" title="Beta-weighted dollar delta">
                    {money(c.beta_weighted_delta_dollars)}
                  </td>
                  <td
                    className={`text-right tabular-nums ${
                      (c.scenario_pnl ?? 0) < 0 ? "text-red-600 dark:text-red-400" : "text-emerald-600 dark:text-emerald-400"
                    }`}
                  >
                    {money(c.scenario_pnl)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}
