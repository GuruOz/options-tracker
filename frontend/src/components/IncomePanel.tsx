import { useEffect, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { getJSON, putJSON, withAccount } from "../api/client";
import type { Income, IncomeMonth } from "../api/types";
import { useAccount } from "../hooks/useAccount";

const money = (v: number | null | undefined, signed = false) => {
  if (v == null) return "—";
  const s = Math.abs(v).toLocaleString(undefined, { maximumFractionDigits: 0 });
  if (v < 0) return `−$${s}`;
  return signed ? `+$${s}` : `$${s}`;
};
const pct = (v: number | null | undefined, d = 0) =>
  v == null ? "—" : `${(v * 100).toFixed(d)}%`;

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
const monthLabel = (mk: string) => {
  const [y, m] = mk.split("-");
  return `${MONTHS[Number(m) - 1] ?? m} ${y}`;
};

/**
 * Fill a continuous month axis between the first and last month present, so the
 * bar chart reads as an unbroken timeline (zero-activity months show an empty
 * slot) instead of silently collapsing the gaps.
 */
function densifyMonths(months: IncomeMonth[]): IncomeMonth[] {
  if (months.length === 0) return months;
  const sorted = [...months].sort((a, b) => a.month.localeCompare(b.month));
  const byKey = new Map(sorted.map((m) => [m.month, m]));
  let [y, mo] = sorted[0].month.split("-").map(Number);
  const [ly, lm] = sorted[sorted.length - 1].month.split("-").map(Number);
  const out: IncomeMonth[] = [];
  while (y < ly || (y === ly && mo <= lm)) {
    const key = `${y}-${String(mo).padStart(2, "0")}`;
    out.push(
      byKey.get(key) ?? { month: key, pnl: 0, chain_count: 0, cashed_out: false, withdrawal: null, note: null }
    );
    if (++mo > 12) { mo = 1; y++; }
  }
  return out;
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
  tone?: "default" | "good" | "bad";
  title?: string;
}) {
  const toneClass =
    tone === "good"
      ? "text-emerald-600 dark:text-emerald-400"
      : tone === "bad"
      ? "text-red-600 dark:text-red-400"
      : "text-slate-800 dark:text-slate-100";
  return (
    <div className="rounded-lg border border-slate-200 p-4 dark:border-slate-700 dark:bg-slate-800" title={title}>
      <div className="text-xs uppercase tracking-wide text-slate-400 dark:text-slate-500">{label}</div>
      <div className={`mt-1 text-2xl font-bold tabular-nums ${toneClass}`}>{value}</div>
      {sub && <div className="mt-0.5 text-xs text-slate-500 dark:text-slate-400">{sub}</div>}
    </div>
  );
}

/** Monthly P&L bars with a zero baseline (no chart lib needed). */
function MonthlyBars({ months }: { months: IncomeMonth[] }) {
  if (months.length === 0) return null;
  const w = Math.max(months.length * 30, 240);
  const h = 130;
  const pad = 22;
  const plotH = h - pad * 2;
  const hasNeg = months.some((m) => m.pnl < 0);
  const maxAbs = Math.max(1, ...months.map((m) => Math.abs(m.pnl)));
  const zeroY = hasNeg ? pad + plotH / 2 : h - pad;
  const scale = (hasNeg ? plotH / 2 : plotH) / maxAbs;
  const colW = (w - pad * 2) / months.length;
  const barW = colW * 0.6;

  return (
    <svg viewBox={`0 0 ${w} ${h}`} className="h-32 w-full" preserveAspectRatio="none">
      <line x1={pad} y1={zeroY} x2={w - pad} y2={zeroY} stroke="currentColor" className="text-slate-200 dark:text-slate-700" strokeWidth={1} />
      {months.map((m, i) => {
        const cx = pad + colW * i + colW / 2;
        const barH = Math.abs(m.pnl) * scale;
        const y = m.pnl >= 0 ? zeroY - barH : zeroY;
        return (
          <g key={m.month}>
            <rect
              x={cx - barW / 2}
              y={y}
              width={barW}
              height={Math.max(barH, 0.5)}
              rx={1.5}
              className={m.pnl >= 0 ? "fill-emerald-500" : "fill-red-500"}
            >
              <title>{`${monthLabel(m.month)}: ${money(m.pnl, true)} (${m.chain_count} chain${m.chain_count === 1 ? "" : "s"})`}</title>
            </rect>
          </g>
        );
      })}
    </svg>
  );
}

function MonthRow({
  m,
  onSave,
  readOnly = false,
}: {
  m: IncomeMonth;
  onSave: (month: string, body: { cashed_out: boolean; withdrawal_amount: number | null; note: string | null }) => void;
  readOnly?: boolean;
}) {
  const [cashedOut, setCashedOut] = useState(m.cashed_out);
  const [withdrawal, setWithdrawal] = useState(m.withdrawal != null ? String(m.withdrawal) : "");
  const [note, setNote] = useState(m.note ?? "");

  useEffect(() => {
    setCashedOut(m.cashed_out);
    setWithdrawal(m.withdrawal != null ? String(m.withdrawal) : "");
    setNote(m.note ?? "");
  }, [m.cashed_out, m.withdrawal, m.note]);

  const save = (patch?: Partial<{ cashed_out: boolean; withdrawal_amount: number | null; note: string | null }>) => {
    onSave(m.month, {
      cashed_out: cashedOut,
      withdrawal_amount: withdrawal === "" ? null : Number(withdrawal),
      note: note.trim() === "" ? null : note.trim(),
      ...patch,
    });
  };

  return (
    <tr className="border-t border-slate-100 dark:border-slate-700">
      <td className="py-1.5 pr-3 font-medium text-slate-700 dark:text-slate-200">{monthLabel(m.month)}</td>
      <td className={`pr-3 text-right tabular-nums ${m.pnl >= 0 ? "text-emerald-600 dark:text-emerald-400" : "text-red-600 dark:text-red-400"}`}>
        {money(m.pnl, true)}
      </td>
      <td className="pr-3 text-right tabular-nums text-slate-400">{m.chain_count}</td>
      <td className="pr-3 text-center">
        <input
          type="checkbox"
          checked={cashedOut}
          disabled={readOnly}
          onChange={(e) => {
            setCashedOut(e.target.checked);
            save({ cashed_out: e.target.checked });
          }}
          className="h-4 w-4 cursor-pointer accent-emerald-600 disabled:cursor-not-allowed disabled:opacity-50"
        />
      </td>
      <td className="pr-3 text-right">
        <input
          type="number"
          inputMode="decimal"
          value={withdrawal}
          placeholder="—"
          disabled={readOnly}
          onChange={(e) => setWithdrawal(e.target.value)}
          onBlur={() => save()}
          className="w-20 rounded border border-slate-200 bg-transparent px-1.5 py-0.5 text-right text-xs tabular-nums focus:border-blue-400 focus:outline-none disabled:cursor-not-allowed disabled:opacity-50 dark:border-slate-600"
        />
      </td>
      <td>
        <input
          type="text"
          value={note}
          placeholder="note…"
          disabled={readOnly}
          onChange={(e) => setNote(e.target.value)}
          onBlur={() => save()}
          className="w-full rounded border border-slate-200 bg-transparent px-1.5 py-0.5 text-xs focus:border-blue-400 focus:outline-none disabled:cursor-not-allowed disabled:opacity-50 dark:border-slate-600"
        />
      </td>
    </tr>
  );
}

export function IncomePanel() {
  const queryClient = useQueryClient();
  const { selected, isAll } = useAccount();
  const { data } = useQuery({
    queryKey: ["income", selected],
    queryFn: () => getJSON<Income>(withAccount("/api/income", selected)),
  });

  if (!data || data.months.length === 0) return null;

  const byAccount = data.by_account ?? [];
  const isCombined = byAccount.length > 0;

  const saveAdjustment = async (
    month: string,
    body: { cashed_out: boolean; withdrawal_amount: number | null; note: string | null }
  ) => {
    if (isAll) return; // guarded in the UI too, but never write against "all"
    await putJSON(withAccount("/api/income/adjustments", selected), { month, ...body });
    queryClient.invalidateQueries({ queryKey: ["income"] });
  };

  const latestYear = data.years[data.years.length - 1];

  return (
    <section className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm dark:border-slate-700 dark:bg-slate-900">
      <div className="mb-3 flex items-baseline justify-between">
        <h2 className="text-base font-semibold text-slate-800 dark:text-slate-100">
          Premium income{isCombined ? " — all accounts" : ""}
        </h2>
        <span className="text-xs text-slate-400 dark:text-slate-500">banked · commission-net · by trade-open month</span>
      </div>
      {isCombined && (
        <p className="mb-3 text-xs text-amber-600 dark:text-amber-400">
          Cashed-out flags and withdrawals are per account — pick a specific account to edit them.
          {" "}Per-account: {byAccount.map((a) => `${a.account_label} ${money(a.all_time, true)}`).join(" · ")}
        </p>
      )}

      <div className="grid grid-cols-2 gap-3 xl:grid-cols-4">
        <Stat
          label="All-time"
          value={money(data.all_time, true)}
          sub={`${data.closed_count} closed · ${data.open_count} open`}
          tone={data.all_time >= 0 ? "good" : "bad"}
          title="Commission-net P&L across every roll chain: finished chains in full, plus what still-open chains have banked from rolling. Premium riding on an open leg is excluded until that leg expires worthless or you buy it back."
        />
        {latestYear && (
          <Stat
            label={`${latestYear.year} YTD`}
            value={money(latestYear.ytd, true)}
            sub={`Withdrawn ${money(latestYear.withdrawn)} · Remaining ${money(latestYear.remaining)}`}
            tone={latestYear.ytd >= 0 ? "good" : "bad"}
            title="This year's income, with manual withdrawals netted out."
          />
        )}
        <Stat
          label="Finished / Open"
          value={money(data.realized, true)}
          sub={`${money(data.unrealized, true)} banked on open chains`}
          tone={data.realized >= 0 ? "good" : "bad"}
          title="First figure: chains that are done. Second: what open chains have banked from rolling so far — each roll banks only the decay on the leg it replaced, and the premium on the leg still open counts for nothing until it expires worthless or you close it."
        />
        <Stat
          label="Win rate"
          value={data.win_rate == null ? "—" : pct(data.win_rate)}
          sub={data.yield_pct != null ? `${pct(data.yield_pct, 1)} of net liq` : undefined}
          title="Share of closed chains that finished profitable."
        />
      </div>

      <div className="mt-4">
        <MonthlyBars months={densifyMonths(data.months)} />
      </div>

      {data.years.length > 0 && (
        <div className="mt-4 grid grid-cols-1 gap-2 sm:grid-cols-2 xl:grid-cols-3">
          {data.years.map((y) => (
            <div key={y.year} className="rounded-lg border border-slate-200 px-4 py-2 text-sm dark:border-slate-700">
              <div className="flex items-baseline justify-between">
                <span className="font-semibold text-slate-700 dark:text-slate-200">{y.year}</span>
                <span className={`tabular-nums ${y.ytd >= 0 ? "text-emerald-600 dark:text-emerald-400" : "text-red-600 dark:text-red-400"}`}>
                  {money(y.ytd, true)}
                </span>
              </div>
              <div className="mt-0.5 flex justify-between text-xs text-slate-500 dark:text-slate-400">
                <span>Withdrawn {money(y.withdrawn)}</span>
                <span>Remaining {money(y.remaining)}</span>
              </div>
            </div>
          ))}
        </div>
      )}

      <div className="mt-4 overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="text-left text-xs uppercase tracking-wide text-slate-400 dark:text-slate-500 border-b border-slate-100 dark:border-slate-700">
              <th className="py-1.5 pr-3">Month</th>
              <th className="pr-3 text-right" title="Banked P&amp;L of the chains opened this month. A chain that's still open contributes only what rolling has banked, not the premium locked in its open leg — so this can keep moving after the month ends.">P&amp;L</th>
              <th className="pr-3 text-right" title="Number of roll chains opened this month.">Chains</th>
              <th className="pr-3 text-center" title="Mark this month's income as moved out of the trading account.">Cashed out?</th>
              <th className="pr-3 text-right" title="Manual withdrawal amount for this month.">Withdrawal</th>
              <th>Note</th>
            </tr>
          </thead>
          <tbody>
            {data.months.map((m) => (
              <MonthRow key={m.month} m={m} onSave={saveAdjustment} readOnly={isCombined} />
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}
