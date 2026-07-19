import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import {
  Area,
  AreaChart,
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  Line,
  LineChart,
  Pie,
  PieChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { getJSON, postJSON, withAccount } from "../api/client";
import type {
  AdvisorConfig,
  AdvisorSuggestion,
  CashflowResponse,
  HoldingsResponse,
  Income,
  NetWorthHistoryResponse,
  NetWorthResponse,
  NetWorthSource,
  PlanSettingsResponse,
  StatementsResponse,
} from "../api/types";
import { fmtCode } from "../lib/money";
import { computeFire } from "../lib/fire";
import { useScope } from "../hooks/useScope";
import { useDisplayCurrency } from "../hooks/useDisplayCurrency";
import { WidgetEmpty, WidgetLoading } from "./WidgetShell";

export const SOURCE_COLORS: Record<string, string> = {
  ibkr: "#10b981",
  cpf: "#3b82f6",
  endowus: "#f59e0b",
};
const PALETTE = [
  "#10b981", "#3b82f6", "#f59e0b", "#8b5cf6",
  "#ec4899", "#14b8a6", "#f43f5e", "#eab308",
];
const SOURCE_LABEL: Record<string, string> = {
  ibkr: "IBKR",
  cpf: "CPF",
  endowus: "Endowus",
};

function fmtMonth(iso: string): string {
  const d = new Date(iso);
  return Number.isNaN(d.getTime())
    ? iso
    : d.toLocaleDateString(undefined, { month: "short", year: "2-digit" });
}

// --- shared data hooks (keyed by scope + currency) ---

function useNetWorth() {
  const { selected } = useScope();
  const { currency } = useDisplayCurrency();
  return useQuery({
    queryKey: ["networth", selected, currency],
    queryFn: () =>
      getJSON<NetWorthResponse>(
        `/api/networth?owner=${encodeURIComponent(selected)}&target=${currency}`,
      ),
  });
}

function useHistory(months: number) {
  const { selected } = useScope();
  const { currency } = useDisplayCurrency();
  return useQuery({
    queryKey: ["networth", "history", selected, currency, months],
    queryFn: () =>
      getJSON<NetWorthHistoryResponse>(
        `/api/networth/history?owner=${encodeURIComponent(selected)}&target=${currency}&months=${months}`,
      ),
  });
}

function useHoldings() {
  const { selected } = useScope();
  const { currency } = useDisplayCurrency();
  return useQuery({
    queryKey: ["holdings", selected, currency],
    queryFn: () =>
      getJSON<HoldingsResponse>(
        `/api/holdings?owner=${encodeURIComponent(selected)}&target=${currency}`,
      ),
  });
}

function useStatements() {
  return useQuery({
    queryKey: ["statements"],
    queryFn: () => getJSON<StatementsResponse>("/api/statements"),
  });
}

function useIncomeAll() {
  return useQuery({
    queryKey: ["income", "all"],
    queryFn: () => getJSON<Income>(withAccount("/api/income", "all")),
  });
}

function planKey(selected: string): string {
  return selected === "all" ? "household" : selected;
}

function usePlanSettings() {
  const { selected } = useScope();
  const key = planKey(selected);
  return useQuery({
    queryKey: ["plan", "settings", key],
    queryFn: () => getJSON<PlanSettingsResponse>(`/api/plan/settings?owner=${encodeURIComponent(key)}`),
  });
}

function useCashflow() {
  const { selected } = useScope();
  const key = planKey(selected);
  return useQuery({
    queryKey: ["cashflow", key],
    queryFn: () => getJSON<CashflowResponse>(`/api/cashflow?owner=${encodeURIComponent(key)}&months=12`),
  });
}

/** Sum each source's converted value across the owners in scope. */
function sourceTotals(data: NetWorthResponse | undefined): Record<string, NetWorthSource> {
  const out: Record<string, NetWorthSource> = {};
  for (const owner of data?.owners ?? []) {
    for (const [kind, src] of Object.entries(owner.sources)) {
      const cur = out[kind];
      if (!cur) {
        out[kind] = {
          ...src,
          breakdown: { ...(src.breakdown ?? {}) },
          by_asset_class: { ...(src.by_asset_class ?? {}) },
        };
      } else {
        cur.converted = (cur.converted ?? 0) + (src.converted ?? 0);
        for (const [c, v] of Object.entries(src.breakdown ?? {}))
          cur.breakdown![c] = (cur.breakdown![c] ?? 0) + v;
        for (const [c, v] of Object.entries(src.by_asset_class ?? {}))
          cur.by_asset_class![c] = (cur.by_asset_class![c] ?? 0) + v;
      }
    }
  }
  return out;
}

// --- widgets ---

export function NetWorthHero() {
  const { currency } = useDisplayCurrency();
  const { data, isLoading } = useNetWorth();
  const { data: hist } = useHistory(12);
  if (isLoading) return <WidgetLoading />;
  if (!data) return <WidgetEmpty text="No data." />;

  const s = hist?.series ?? [];
  const delta =
    s.length >= 2 ? s[s.length - 1].total - s[s.length - 2].total : null;

  return (
    <div>
      <p className="text-3xl font-bold text-slate-900 dark:text-slate-50">
        {fmtCode(data.combined.total_converted, currency)}
      </p>
      {delta != null && (
        <p className={`mt-1 text-xs font-semibold ${delta >= 0 ? "text-emerald-600" : "text-red-500"}`}>
          {fmtCode(delta, currency, { signed: true })} this month
        </p>
      )}
      <div className="mt-3 flex flex-wrap gap-x-5 gap-y-1">
        {data.owners.map((o) => (
          <span key={o.owner} className="text-xs text-slate-500 dark:text-slate-400">
            {o.label}:{" "}
            <span className="font-semibold text-slate-700 dark:text-slate-200">
              {fmtCode(o.total_converted, currency)}
            </span>
          </span>
        ))}
      </div>
    </div>
  );
}

export function SourceCard({ config }: { config: { source?: string } }) {
  const kind = config.source ?? "ibkr";
  const { currency } = useDisplayCurrency();
  const { data, isLoading } = useNetWorth();
  if (isLoading) return <WidgetLoading />;
  const src = sourceTotals(data)[kind];
  if (!src) return <WidgetEmpty text={`No ${SOURCE_LABEL[kind] ?? kind} data.`} />;

  return (
    <div>
      <p className="text-2xl font-bold text-slate-900 dark:text-slate-50">
        {fmtCode(src.converted, currency)}
      </p>
      {src.breakdown && Object.keys(src.breakdown).length > 0 && (
        <div className="mt-2 space-y-0.5">
          {Object.entries(src.breakdown).map(([c, v]) => (
            <div key={c} className="flex justify-between text-xs">
              <span className="text-slate-500 dark:text-slate-400">{c}</span>
              <span className="font-medium text-slate-700 dark:text-slate-200">
                {fmtCode(v, src.currency)}
              </span>
            </div>
          ))}
        </div>
      )}
      {src.as_of && (
        <p className="mt-2 text-[11px] text-slate-400 dark:text-slate-500">
          as of {new Date(src.as_of).toLocaleDateString()}
        </p>
      )}
    </div>
  );
}

export function AllocationDonut({ config }: { config: { groupBy?: string } }) {
  const groupBy = config.groupBy ?? "source";
  const { currency } = useDisplayCurrency();
  const { data, isLoading } = useNetWorth();
  if (isLoading) return <WidgetLoading />;
  const totals = sourceTotals(data);

  let slices: { name: string; value: number }[] = [];
  if (groupBy === "source") {
    slices = Object.entries(totals).map(([k, s]) => ({
      name: SOURCE_LABEL[k] ?? k,
      value: s.converted ?? 0,
    }));
  } else {
    // by asset: CPF sub-accounts + Endowus asset classes + IBKR as one slice
    if (totals.ibkr?.converted) slices.push({ name: "IBKR", value: totals.ibkr.converted });
    for (const [c, v] of Object.entries(totals.cpf?.breakdown ?? {}))
      slices.push({ name: `CPF ${c}`, value: v });
    for (const [c, v] of Object.entries(totals.endowus?.by_asset_class ?? {}))
      slices.push({ name: c, value: v });
  }
  slices = slices.filter((s) => s.value > 0);
  if (slices.length === 0) return <WidgetEmpty text="No allocation data." />;

  return (
    <ResponsiveContainer width="100%" height="100%">
      <PieChart>
        <Pie data={slices} dataKey="value" nameKey="name" innerRadius="55%" outerRadius="85%" paddingAngle={2}>
          {slices.map((_, i) => (
            <Cell key={i} fill={PALETTE[i % PALETTE.length]} />
          ))}
        </Pie>
        <Tooltip formatter={(v) => fmtCode(Number(v), currency)} />
      </PieChart>
    </ResponsiveContainer>
  );
}

function TrendChart({ months, currency }: { months: number; currency: string }) {
  const { data } = useHistory(months);
  const series = data?.series ?? [];
  if (series.length === 0) return <WidgetEmpty text="No history yet." />;
  return (
    <ResponsiveContainer width="100%" height="100%">
      <AreaChart data={series} margin={{ top: 4, right: 4, bottom: 0, left: 0 }}>
        <CartesianGrid strokeDasharray="3 3" stroke="currentColor" className="text-slate-200 dark:text-slate-700" />
        <XAxis dataKey="month" tickFormatter={fmtMonth} tick={{ fontSize: 10 }} minTickGap={24} />
        <YAxis tick={{ fontSize: 10 }} width={44} tickFormatter={(v) => `${Math.round(v / 1000)}k`} />
        <Tooltip
          formatter={(v, n) => [fmtCode(Number(v), currency), SOURCE_LABEL[String(n)] ?? String(n)]}
          labelFormatter={(l) => fmtMonth(String(l))}
        />
        {(["ibkr", "cpf", "endowus"] as const).map((k) => (
          <Area key={k} type="monotone" dataKey={k} stackId="1" stroke={SOURCE_COLORS[k]} fill={SOURCE_COLORS[k]} fillOpacity={0.25} />
        ))}
      </AreaChart>
    </ResponsiveContainer>
  );
}

export function NetWorthTrend({ config }: { config: { months?: number } }) {
  const { currency } = useDisplayCurrency();
  return <TrendChart months={config.months ?? 24} currency={currency} />;
}

export function EndowusHoldings() {
  const { data, isLoading } = useHoldings();
  if (isLoading) return <WidgetLoading />;
  const rows = (data?.holdings ?? []).slice(0, 6);
  if (rows.length === 0) return <WidgetEmpty text="No Endowus holdings." />;
  return (
    <table className="min-w-full text-xs">
      <tbody className="divide-y divide-slate-100 dark:divide-slate-800">
        {rows.map((h, i) => (
          <tr key={i} className="text-slate-700 dark:text-slate-200">
            <td className="py-1 pr-2 font-medium">{h.fund_name}</td>
            <td className="py-1 pr-2 text-right">{fmtCode(h.market_value, h.currency)}</td>
            <td className="py-1 text-right text-slate-400">{h.allocation_pct != null ? `${h.allocation_pct}%` : ""}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

export function StatementStaleness() {
  const { data } = useStatements();
  const now = Date.now();
  const stale = (data?.statements ?? []).filter((s) => {
    if (!s.period_end) return false;
    const age = (now - new Date(s.period_end).getTime()) / 86_400_000;
    return age > 40;
  });
  // Keep only the newest per account so we flag each source once.
  const seen = new Set<string>();
  const flagged = stale.filter((s) => (seen.has(s.account_id) ? false : seen.add(s.account_id)));

  if (flagged.length === 0) {
    return <WidgetEmpty text="All statements are up to date." />;
  }
  return (
    <div className="space-y-1">
      {flagged.map((s) => (
        <div key={s.id} className="text-xs text-amber-700 dark:text-amber-300">
          {s.account_id} — last statement {new Date(s.period_end!).toLocaleDateString()}
        </div>
      ))}
      <Link to="/uploads" className="mt-1 inline-block text-xs font-semibold text-blue-600 hover:underline dark:text-blue-400">
        Upload newer →
      </Link>
    </div>
  );
}

export function OptionsSnapshot() {
  const { data, isLoading } = useIncomeAll();
  if (isLoading) return <WidgetLoading />;
  const thisMonth = data?.months?.[data.months.length - 1];
  const ccy = data?.premium_currency ?? data?.base_currency ?? "USD";
  return (
    <div>
      <div className="flex gap-6">
        <div>
          <p className="text-xs text-slate-400 dark:text-slate-500">Open positions</p>
          <p className="text-xl font-bold text-slate-900 dark:text-slate-50">{data?.open_count ?? "—"}</p>
        </div>
        <div>
          <p className="text-xs text-slate-400 dark:text-slate-500">This month</p>
          <p className="text-xl font-bold text-emerald-600">{fmtCode(thisMonth?.pnl ?? null, ccy)}</p>
        </div>
      </div>
      <Link to="/options" className="mt-2 inline-block text-xs font-semibold text-blue-600 hover:underline dark:text-blue-400">
        Open options tracker →
      </Link>
    </div>
  );
}

export function FireProgress() {
  const { currency } = useDisplayCurrency();
  const settings = usePlanSettings();
  const nw = useNetWorth();
  const cashflow = useCashflow();
  if (settings.isLoading || nw.isLoading) return <WidgetLoading />;
  if (!settings.data || !nw.data) return <WidgetEmpty text="Set up your plan first." />;

  const latest = cashflow.data?.entries?.[cashflow.data.entries.length - 1];
  const latestSavings =
    latest && latest.income != null && latest.expenses != null
      ? latest.income - latest.expenses
      : null;
  const fire = computeFire(settings.data.data, nw.data.combined.total_converted ?? 0, latestSavings);
  const pct = Math.max(0, Math.min(100, fire.progressPct));

  return (
    <div>
      <div className="flex items-baseline justify-between">
        <span className="text-2xl font-bold text-slate-900 dark:text-slate-50">{pct.toFixed(0)}%</span>
        <span className={`text-xs font-semibold ${fire.onTrack ? "text-emerald-600" : "text-amber-600"}`}>
          {fire.onTrack ? "On track" : "Behind"}
        </span>
      </div>
      <div className="mt-2 h-2 w-full rounded-full bg-slate-100 dark:bg-slate-800">
        <div className="h-2 rounded-full bg-emerald-500" style={{ width: `${pct}%` }} />
      </div>
      <p className="mt-2 text-xs text-slate-400 dark:text-slate-500">
        FIRE number {fmtCode(fire.fireNumber, currency)}
        {fire.yearsToFire != null ? ` · ~${fire.yearsToFire} yrs` : ""}
      </p>
      <Link to="/plan" className="mt-1 inline-block text-xs font-semibold text-blue-600 hover:underline dark:text-blue-400">
        Open FIRE plan →
      </Link>
    </div>
  );
}

export function SavingsRate() {
  const { currency } = useDisplayCurrency();
  const cashflow = useCashflow();
  const entries = cashflow.data?.entries ?? [];
  const latest = entries[entries.length - 1];
  if (!latest || latest.income == null || latest.expenses == null) {
    return <WidgetEmpty text="Add this month's income & expenses on the Plan page." />;
  }
  const savings = latest.income - latest.expenses;
  const rate = latest.income > 0 ? (savings / latest.income) * 100 : 0;
  const spark = entries.slice(-6).map((e) => ({
    month: e.month,
    v: e.income != null && e.expenses != null ? e.income - e.expenses : 0,
  }));
  return (
    <div>
      <p className="text-2xl font-bold text-slate-900 dark:text-slate-50">{rate.toFixed(0)}%</p>
      <p className="text-xs text-slate-400 dark:text-slate-500">
        {fmtCode(savings, currency)} saved this month
      </p>
      {spark.length > 1 && (
        <div className="mt-2 h-12 w-full">
          <ResponsiveContainer width="100%" height="100%">
            <BarChart data={spark}>
              <Bar dataKey="v" fill="#10b981" />
            </BarChart>
          </ResponsiveContainer>
        </div>
      )}
    </div>
  );
}

export function AiSuggestions() {
  const { selected } = useScope();
  const qc = useQueryClient();
  const config = useQuery({
    queryKey: ["advisor", "config"],
    queryFn: () => getJSON<AdvisorConfig>("/api/advisor/config"),
  });
  const latest = useQuery({
    queryKey: ["advisor", "latest", selected],
    queryFn: () => getJSON<AdvisorSuggestion>(`/api/advisor/latest?owner=${encodeURIComponent(selected)}`),
  });
  const generate = useMutation({
    mutationFn: () => postJSON<AdvisorSuggestion>(`/api/advisor/generate?owner=${encodeURIComponent(selected)}`, {}),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["advisor", "latest", selected] }),
  });

  const keySet = config.data?.key_set;
  const content = latest.data?.content;

  return (
    <div className="flex h-full flex-col">
      {!keySet ? (
        <p className="text-xs text-slate-500 dark:text-slate-400">
          Add an API key in{" "}
          <Link to="/settings" className="font-semibold text-blue-600 hover:underline dark:text-blue-400">
            Settings
          </Link>{" "}
          to generate suggestions.
        </p>
      ) : content ? (
        <div className="min-h-0 flex-1 overflow-auto whitespace-pre-wrap text-xs text-slate-600 dark:text-slate-300">
          {content.length > 600 ? content.slice(0, 600) + "…" : content}
        </div>
      ) : (
        <p className="text-xs text-slate-400 dark:text-slate-500">No suggestions yet.</p>
      )}
      {keySet && (
        <div className="mt-2 flex items-center gap-2">
          <button
            onClick={() => generate.mutate()}
            disabled={generate.isPending}
            className="rounded-lg bg-blue-600 px-3 py-1 text-xs font-semibold text-white hover:bg-blue-700 disabled:opacity-50"
          >
            {generate.isPending ? "Generating…" : content ? "Regenerate" : "Generate"}
          </button>
          <span className="text-[10px] text-slate-400">Educational, not advice.</span>
        </div>
      )}
    </div>
  );
}

// --- custom chart: metric x chart type ---

const CHART_METRICS: Record<string, { label: string }> = {
  networth_total: { label: "Net worth (total)" },
  networth_by_source: { label: "Net worth by source" },
  premium_income: { label: "Options premium / month" },
  savings: { label: "Monthly savings" },
};

export function CustomChart({
  config,
}: {
  config: { metric?: string; chartType?: string; months?: number };
}) {
  const metric = config.metric ?? "networth_total";
  const chartType = config.chartType ?? "area";
  const months = config.months ?? 24;
  const { currency } = useDisplayCurrency();

  const hist = useHistory(months);
  const income = useIncomeAll();
  const cashflow = useCashflow();

  let series: Record<string, unknown>[] = [];
  let keys: string[] = [];
  if (metric === "premium_income") {
    series = (income.data?.months ?? []).slice(-months).map((m) => ({ month: m.month, value: m.pnl }));
    keys = ["value"];
  } else if (metric === "savings") {
    series = (cashflow.data?.entries ?? [])
      .slice(-months)
      .map((e) => ({
        month: e.month,
        value: e.income != null && e.expenses != null ? e.income - e.expenses : 0,
      }));
    keys = ["value"];
  } else if (metric === "networth_by_source") {
    series = (hist.data?.series ?? []) as unknown as Record<string, unknown>[];
    keys = ["ibkr", "cpf", "endowus"];
  } else {
    series = (hist.data?.series ?? []).map((p) => ({ month: p.month, value: p.total }));
    keys = ["value"];
  }
  if (series.length === 0) return <WidgetEmpty text="No data for this metric yet." />;

  const color = (k: string, i: number) => SOURCE_COLORS[k] ?? PALETTE[i % PALETTE.length];
  const common = (
    <>
      <CartesianGrid strokeDasharray="3 3" stroke="currentColor" className="text-slate-200 dark:text-slate-700" />
      <XAxis dataKey="month" tickFormatter={fmtMonth} tick={{ fontSize: 10 }} minTickGap={24} />
      <YAxis tick={{ fontSize: 10 }} width={44} tickFormatter={(v) => `${Math.round(Number(v) / 1000)}k`} />
      <Tooltip
        formatter={(v, n) => [fmtCode(Number(v), currency), SOURCE_LABEL[String(n)] ?? String(n)]}
        labelFormatter={(l) => fmtMonth(String(l))}
      />
    </>
  );

  return (
    <ResponsiveContainer width="100%" height="100%">
      {chartType === "bar" ? (
        <BarChart data={series} margin={{ top: 4, right: 4, bottom: 0, left: 0 }}>
          {common}
          {keys.map((k, i) => (
            <Bar key={k} dataKey={k} stackId="1" fill={color(k, i)} />
          ))}
        </BarChart>
      ) : chartType === "line" ? (
        <LineChart data={series} margin={{ top: 4, right: 4, bottom: 0, left: 0 }}>
          {common}
          {keys.map((k, i) => (
            <Line key={k} type="monotone" dataKey={k} stroke={color(k, i)} dot={false} />
          ))}
        </LineChart>
      ) : (
        <AreaChart data={series} margin={{ top: 4, right: 4, bottom: 0, left: 0 }}>
          {common}
          {keys.map((k, i) => (
            <Area key={k} type="monotone" dataKey={k} stackId="1" stroke={color(k, i)} fill={color(k, i)} fillOpacity={0.25} />
          ))}
        </AreaChart>
      )}
    </ResponsiveContainer>
  );
}

export { CHART_METRICS };
