import { useEffect, useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  Area,
  ComposedChart,
  CartesianGrid,
  Line,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { getJSON, putJSON } from "../api/client";
import type {
  CashflowResponse,
  PlanSettings,
  PlanSettingsResponse,
} from "../api/types";
import { fmtCode } from "../lib/money";
import { computeFire } from "../lib/fire";
import { useScope } from "../hooks/useScope";
import { useDisplayCurrency } from "../hooks/useDisplayCurrency";
import type { NetWorthResponse } from "../api/types";

function planKey(selected: string): string {
  return selected === "all" ? "household" : selected;
}

const FIELDS: { key: keyof PlanSettings; label: string; min: number; max: number; step: number }[] = [
  { key: "current_age", label: "Current age", min: 18, max: 80, step: 1 },
  { key: "retire_age", label: "Retirement age", min: 30, max: 90, step: 1 },
  { key: "target_monthly_income", label: "Target monthly income", min: 0, max: 50000, step: 100 },
  { key: "swr_pct", label: "Withdrawal rate %", min: 2, max: 8, step: 0.1 },
  { key: "expected_return_pct", label: "Expected return %", min: 0, max: 15, step: 0.1 },
  { key: "pessimistic_return_pct", label: "Pessimistic return %", min: 0, max: 15, step: 0.1 },
  { key: "optimistic_return_pct", label: "Optimistic return %", min: 0, max: 15, step: 0.1 },
];

function Card({ children, className = "" }: { children: React.ReactNode; className?: string }) {
  return (
    <div className={`rounded-xl border border-slate-200 bg-white px-5 py-4 shadow-sm dark:border-slate-700 dark:bg-slate-900 ${className}`}>
      {children}
    </div>
  );
}

export function PlanPage() {
  const { selected } = useScope();
  const { currency } = useDisplayCurrency();
  const key = planKey(selected);

  const settingsQ = useQuery({
    queryKey: ["plan", "settings", key],
    queryFn: () => getJSON<PlanSettingsResponse>(`/api/plan/settings?owner=${encodeURIComponent(key)}`),
  });
  const cashflowQ = useQuery({
    queryKey: ["cashflow", key],
    queryFn: () => getJSON<CashflowResponse>(`/api/cashflow?owner=${encodeURIComponent(key)}&months=12`),
  });
  const networthQ = useQuery({
    queryKey: ["networth", selected, currency],
    queryFn: () => getJSON<NetWorthResponse>(`/api/networth?owner=${encodeURIComponent(selected)}&target=${currency}`),
  });

  const [settings, setSettings] = useState<PlanSettings | null>(null);
  useEffect(() => {
    if (settingsQ.data) setSettings(settingsQ.data.data);
  }, [settingsQ.data]);

  const save = (next: PlanSettings) => {
    setSettings(next);
    void putJSON(`/api/plan/settings?owner=${encodeURIComponent(key)}`, next).catch(() => {});
  };

  const currentNetWorth = networthQ.data?.combined.total_converted ?? 0;
  const latest = cashflowQ.data?.entries?.[cashflowQ.data.entries.length - 1];
  const latestSavings =
    latest && latest.income != null && latest.expenses != null
      ? latest.income - latest.expenses
      : null;

  const fire = useMemo(
    () => (settings ? computeFire(settings, currentNetWorth, latestSavings) : null),
    [settings, currentNetWorth, latestSavings],
  );

  if (!settings || !fire) {
    return <p className="text-sm text-slate-400 dark:text-slate-500">Loading plan…</p>;
  }

  const bandData = fire.points.map((p) => ({
    age: p.age,
    expected: p.expected,
    lower: p.pessimistic,
    band: p.optimistic - p.pessimistic, // stacked on top of lower => shaded envelope
  }));

  return (
    <div className="space-y-6">
      <div className="grid gap-4 lg:grid-cols-4">
        <Stat label="FIRE number" value={fmtCode(fire.fireNumber, currency)} />
        <Stat
          label="Progress"
          value={`${fire.progressPct.toFixed(0)}%`}
          sub={<Progress pct={fire.progressPct} />}
        />
        <Stat
          label="On track?"
          value={fire.onTrack ? "On track" : "Behind"}
          tone={fire.onTrack ? "good" : "bad"}
          subText={fire.yearsToFire != null ? `FIRE in ~${fire.yearsToFire} yrs` : "Not reached in horizon"}
        />
        <Stat
          label="Monthly savings"
          value={fmtCode(fire.monthlySavings, currency)}
          subText={settings.monthly_savings_override != null ? "override" : "from cashflow"}
        />
      </div>

      <Card>
        <h2 className="mb-3 text-sm font-semibold text-slate-700 dark:text-slate-200">
          Projection · {currency}
        </h2>
        <div className="h-80 w-full">
          <ResponsiveContainer width="100%" height="100%">
            <ComposedChart data={bandData} margin={{ top: 4, right: 12, bottom: 0, left: 8 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="currentColor" className="text-slate-200 dark:text-slate-700" />
              <XAxis dataKey="age" tick={{ fontSize: 11 }} tickFormatter={(v) => `${v}`} />
              <YAxis tick={{ fontSize: 11 }} width={64} tickFormatter={(v) => `${Math.round(v / 1000)}k`} />
              <Tooltip
                formatter={(v, n) => [fmtCode(Number(v), currency), String(n)]}
                labelFormatter={(l) => `Age ${l}`}
              />
              {/* invisible baseline + shaded band between pessimistic and optimistic */}
              <Area dataKey="lower" stackId="band" stroke="none" fill="none" name="Pessimistic" />
              <Area dataKey="band" stackId="band" stroke="none" fill="#3b82f6" fillOpacity={0.12} name="Optimistic range" />
              <Line dataKey="expected" stroke="#10b981" strokeWidth={2} dot={false} name="Expected" />
              <ReferenceLine
                y={fire.fireNumber}
                stroke="#f59e0b"
                strokeDasharray="4 4"
                label={{ value: "FIRE", position: "insideTopRight", fontSize: 11, fill: "#f59e0b" }}
              />
              <ReferenceLine
                x={settings.retire_age}
                stroke="#94a3b8"
                strokeDasharray="4 4"
                label={{ value: "Retire", position: "top", fontSize: 11, fill: "#94a3b8" }}
              />
            </ComposedChart>
          </ResponsiveContainer>
        </div>
      </Card>

      <div className="grid gap-4 lg:grid-cols-2">
        <Card>
          <h2 className="mb-3 text-sm font-semibold text-slate-700 dark:text-slate-200">Plan settings</h2>
          <div className="space-y-4">
            {FIELDS.map((f) => (
              <div key={f.key}>
                <div className="flex justify-between text-xs">
                  <span className="text-slate-500 dark:text-slate-400">{f.label}</span>
                  <span className="font-semibold text-slate-700 dark:text-slate-200">
                    {settings[f.key]}
                  </span>
                </div>
                <input
                  type="range"
                  min={f.min}
                  max={f.max}
                  step={f.step}
                  value={Number(settings[f.key] ?? 0)}
                  onChange={(e) => save({ ...settings, [f.key]: Number(e.target.value) })}
                  className="mt-1 w-full accent-blue-600"
                />
              </div>
            ))}
            <label className="block">
              <span className="text-xs text-slate-500 dark:text-slate-400">
                Monthly savings override (blank = use cashflow)
              </span>
              <input
                type="number"
                value={settings.monthly_savings_override ?? ""}
                onChange={(e) =>
                  save({
                    ...settings,
                    monthly_savings_override: e.target.value === "" ? null : Number(e.target.value),
                  })
                }
                className="mt-1 w-full rounded-lg border border-slate-300 bg-white px-3 py-1.5 text-sm dark:border-slate-600 dark:bg-slate-800 dark:text-slate-100"
              />
            </label>
          </div>
        </Card>

        <CashflowEditor ownerKey={key} currency={currency} />
      </div>

      <p className="text-xs text-slate-400 dark:text-slate-500">
        Projections compound your current net worth ({fmtCode(currentNetWorth, currency)}) plus
        monthly savings. Educational estimates, not financial advice.
      </p>
    </div>
  );
}

function Stat({
  label,
  value,
  sub,
  subText,
  tone,
}: {
  label: string;
  value: string;
  sub?: React.ReactNode;
  subText?: string;
  tone?: "good" | "bad";
}) {
  const toneClass = tone === "good" ? "text-emerald-600" : tone === "bad" ? "text-amber-600" : "text-slate-900 dark:text-slate-50";
  return (
    <Card>
      <p className="text-xs uppercase tracking-wide text-slate-400 dark:text-slate-500">{label}</p>
      <p className={`mt-1 text-xl font-bold ${toneClass}`}>{value}</p>
      {sub}
      {subText && <p className="mt-1 text-xs text-slate-400 dark:text-slate-500">{subText}</p>}
    </Card>
  );
}

function Progress({ pct }: { pct: number }) {
  const w = Math.max(0, Math.min(100, pct));
  return (
    <div className="mt-2 h-2 w-full rounded-full bg-slate-100 dark:bg-slate-800">
      <div className="h-2 rounded-full bg-emerald-500" style={{ width: `${w}%` }} />
    </div>
  );
}

function CashflowEditor({ ownerKey, currency }: { ownerKey: string; currency: string }) {
  const cashflowQ = useQuery({
    queryKey: ["cashflow", ownerKey],
    queryFn: () => getJSON<CashflowResponse>(`/api/cashflow?owner=${encodeURIComponent(ownerKey)}&months=12`),
  });

  const thisMonth = new Date();
  const monthStr = `${thisMonth.getFullYear()}-${String(thisMonth.getMonth() + 1).padStart(2, "0")}-01`;
  const entries = cashflowQ.data?.entries ?? [];
  const current = entries.find((e) => e.month === monthStr);

  const [income, setIncome] = useState("");
  const [expenses, setExpenses] = useState("");
  useEffect(() => {
    setIncome(current?.income != null ? String(current.income) : "");
    setExpenses(current?.expenses != null ? String(current.expenses) : "");
  }, [current?.income, current?.expenses]);

  const saveMonth = () => {
    void putJSON(`/api/cashflow?owner=${encodeURIComponent(ownerKey)}`, {
      month: monthStr,
      income: income === "" ? null : Number(income),
      expenses: expenses === "" ? null : Number(expenses),
    })
      .then(() => cashflowQ.refetch())
      .catch(() => {});
  };

  return (
    <Card>
      <h2 className="mb-3 text-sm font-semibold text-slate-700 dark:text-slate-200">
        This month's cashflow
      </h2>
      <div className="flex flex-wrap items-end gap-3">
        <label className="flex-1">
          <span className="text-xs text-slate-500 dark:text-slate-400">Income</span>
          <input
            type="number"
            value={income}
            onChange={(e) => setIncome(e.target.value)}
            className="mt-1 w-full rounded-lg border border-slate-300 bg-white px-3 py-1.5 text-sm dark:border-slate-600 dark:bg-slate-800 dark:text-slate-100"
          />
        </label>
        <label className="flex-1">
          <span className="text-xs text-slate-500 dark:text-slate-400">Expenses</span>
          <input
            type="number"
            value={expenses}
            onChange={(e) => setExpenses(e.target.value)}
            className="mt-1 w-full rounded-lg border border-slate-300 bg-white px-3 py-1.5 text-sm dark:border-slate-600 dark:bg-slate-800 dark:text-slate-100"
          />
        </label>
        <button
          onClick={saveMonth}
          className="rounded-lg bg-blue-600 px-3 py-1.5 text-sm font-semibold text-white hover:bg-blue-700"
        >
          Save
        </button>
      </div>
      {entries.length > 0 && (
        <div className="mt-4 space-y-1">
          {entries.slice(-6).map((e) => {
            const s = e.income != null && e.expenses != null ? e.income - e.expenses : null;
            return (
              <div key={e.month} className="flex justify-between text-xs">
                <span className="text-slate-500 dark:text-slate-400">
                  {new Date(e.month).toLocaleDateString(undefined, { month: "short", year: "2-digit" })}
                </span>
                <span className="font-medium text-slate-700 dark:text-slate-200">
                  {s != null ? `${fmtCode(s, currency)} saved` : "—"}
                </span>
              </div>
            );
          })}
        </div>
      )}
    </Card>
  );
}
