import { useEffect, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { getJSON } from "../api/client";
import type { Income, IncomeMonth } from "../api/types";

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
}: {
  m: IncomeMonth;
  onSave: (month: string, body: { cashed_out: boolean; withdrawal_amount: number | null; note: string | null }) => void;
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
          onChange={(e) => {
            setCashedOut(e.target.checked);
            save({ cashed_out: e.target.checked });
          }}
          className="h-4 w-4 cursor-pointer accent-emerald-600"
        />
      </td>
      <td className="pr-3 text-right">
        <input
          type="number"
          inputMode="decimal"
          value={withdrawal}
          placeholder="—"
          onChange={(e) => setWithdrawal(e.target.value)}
          onBlur={() => save()}
          className="w-20 rounded border border-slate-200 bg-transparent px-1.5 py-0.5 text-right text-xs tabular-nums focus:border-blue-400 focus:outline-none dark:border-slate-600"
        />
      </td>
      <td>
        <input
          type="text"
          value={note}
          placeholder="note…"
          onChange={(e) => setNote(e.target.value)}
          onBlur={() => save()}
          className="w-full rounded border border-slate-200 bg-transparent px-1.5 py-0.5 text-xs focus:border-blue-400 focus:outline-none dark:border-slate-600"
        />
      </td>
    </tr>
  );
}

export function IncomePanel() {
  const queryClient = useQueryClient();
  const { data } = useQuery({
    queryKey: ["income"],
    queryFn: () => getJSON<Income>("/api/income"),
  });

  if (!data || data.months.length === 0) return null;

  const saveAdjustment = async (
    month: string,
    body: { cashed_out: boolean; withdrawal_amount: number | null; note: string | null }
  ) => {
    await fetch("/api/income/adjustments", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ month, ...body }),
    });
    queryClient.invalidateQueries({ queryKey: ["income"] });
  };

  const latestYear = data.years[data.years.length - 1];

  return (
    <section className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm dark:border-slate-700 dark:bg-slate-900">
      <div className="mb-3 flex items-baseline justify-between">
        <h2 className="text-base font-semibold text-slate-800 dark:text-slate-100">Premium income</h2>
        <span className="text-xs text-slate-400 dark:text-slate-500">commission-net · by trade-open month</span>
      </div>

      <div className="grid grid-cols-2 gap-3 xl:grid-cols-4">
        <Stat
          label="All-time"
          value={money(data.all_time, true)}
          sub={`${data.closed_count} closed · ${data.open_count} open`}
          tone={data.all_time >= 0 ? "good" : "bad"}
          title="Commission-net P&L across every roll chain (realized + open running credit)."
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
          label="Realized / Open"
          value={money(data.realized, true)}
          sub={`${money(data.unrealized, true)} unrealized`}
          tone={data.realized >= 0 ? "good" : "bad"}
          title="Realized = closed chains. Unrealized = running credit on still-open chains."
        />
        <Stat
          label="Win rate"
          value={data.win_rate == null ? "—" : pct(data.win_rate)}
          sub={data.yield_pct != null ? `${pct(data.yield_pct, 1)} of net liq` : undefined}
          title="Share of closed chains that finished profitable."
        />
      </div>

      <div className="mt-4">
        <MonthlyBars months={data.months} />
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
              <th className="pr-3 text-right">P&amp;L</th>
              <th className="pr-3 text-right" title="Number of roll chains opened this month.">Chains</th>
              <th className="pr-3 text-center" title="Mark this month's income as moved out of the trading account.">Cashed out?</th>
              <th className="pr-3 text-right" title="Manual withdrawal amount for this month.">Withdrawal</th>
              <th>Note</th>
            </tr>
          </thead>
          <tbody>
            {data.months.map((m) => (
              <MonthRow key={m.month} m={m} onSave={saveAdjustment} />
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}
