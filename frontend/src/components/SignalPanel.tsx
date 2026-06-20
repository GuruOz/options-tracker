import { useQuery } from "@tanstack/react-query";
import { getJSON } from "../api/client";
import type { Signal, SignalSubScores } from "../api/types";

const VERDICT: Record<string, { bar: string; pill: string }> = {
  FAVORABLE: { bar: "bg-emerald-500", pill: "bg-emerald-100 text-emerald-800 dark:bg-emerald-900 dark:text-emerald-300" },
  SELECTIVE: { bar: "bg-amber-500", pill: "bg-amber-100 text-amber-800 dark:bg-amber-900 dark:text-amber-300" },
  WAIT: { bar: "bg-slate-400", pill: "bg-slate-200 text-slate-700 dark:bg-slate-700 dark:text-slate-200" },
};

const SUBS: { key: keyof SignalSubScores; label: string }[] = [
  { key: "iv_percentile", label: "IV %ile" },
  { key: "variance_premium", label: "Var. premium" },
  { key: "trend", label: "Trend" },
  { key: "rsi_drawdown", label: "RSI / pullback" },
];

const clamp = (v: number) => Math.max(0, Math.min(100, v));
const round = (v: number | null) => (v == null ? "—" : Math.round(v).toString());

export function SignalPanel() {
  const { data } = useQuery({
    queryKey: ["signals"],
    queryFn: () => getJSON<Signal[]>("/api/signals"),
  });
  const rows = data ?? [];

  return (
    <section className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm dark:border-slate-700 dark:bg-slate-900">
      <div className="mb-3 flex items-baseline justify-between">
        <h2 className="text-base font-semibold text-slate-800 dark:text-slate-100">
          Is now a good time to sell?
        </h2>
        <span className="text-xs text-slate-400 dark:text-slate-500">decision aid — not advice</span>
      </div>

      {rows.length === 0 ? (
        <p className="text-sm text-slate-500 dark:text-slate-400">
          No signal yet — the first market poll runs shortly after positions load.
        </p>
      ) : (
        <div className="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-3">
          {rows.map((s) => {
            const style = VERDICT[s.verdict ?? "WAIT"] ?? VERDICT.WAIT;
            const score = s.composite_score;
            return (
              <div
                key={s.underlying_conid}
                className="rounded-lg border border-slate-200 p-4 dark:border-slate-700 dark:bg-slate-800"
              >
                <div className="flex items-center justify-between">
                  <span className="font-semibold text-slate-800 dark:text-slate-100">
                    {s.symbol ?? s.underlying_conid}
                  </span>
                  <span
                    className={`rounded-full px-2 py-0.5 text-xs font-semibold ${style.pill}`}
                  >
                    {s.verdict ?? "—"}
                  </span>
                </div>

                <div className="mt-2 flex items-end gap-2">
                  <span className="text-3xl font-bold tabular-nums text-slate-800 dark:text-slate-100">
                    {round(score)}
                  </span>
                  <span className="mb-1 text-xs text-slate-400 dark:text-slate-500">/ 100</span>
                </div>
                <div className="mt-1 h-2 w-full rounded-full bg-slate-100 dark:bg-slate-700">
                  <div
                    className={`h-2 rounded-full ${style.bar}`}
                    style={{ width: `${score == null ? 0 : clamp(score)}%` }}
                  />
                </div>

                <dl className="mt-3 space-y-1.5">
                  {SUBS.map((sub) => {
                    const val = s.sub_scores?.[sub.key] ?? null;
                    return (
                      <div key={sub.key} className="flex items-center gap-2 text-xs">
                        <dt className="w-24 shrink-0 text-slate-500 dark:text-slate-400">{sub.label}</dt>
                        <div className="h-1.5 flex-1 rounded-full bg-slate-100 dark:bg-slate-700">
                          <div
                            className="h-1.5 rounded-full bg-slate-400 dark:bg-slate-500"
                            style={{ width: `${val == null ? 0 : clamp(val)}%` }}
                          />
                        </div>
                        <dd className="w-7 text-right tabular-nums text-slate-500 dark:text-slate-400">
                          {round(val)}
                        </dd>
                      </div>
                    );
                  })}
                </dl>
              </div>
            );
          })}
        </div>
      )}
    </section>
  );
}
