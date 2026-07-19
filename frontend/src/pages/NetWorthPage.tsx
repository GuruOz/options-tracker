import { useQuery } from "@tanstack/react-query";
import {
  Area,
  AreaChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { getJSON } from "../api/client";
import type {
  HoldingsResponse,
  NetWorthHistoryResponse,
  NetWorthResponse,
  NetWorthSource,
} from "../api/types";
import { fmtCode } from "../lib/money";
import { useScope } from "../hooks/useScope";
import { useDisplayCurrency } from "../hooks/useDisplayCurrency";

const SOURCE_COLORS: Record<string, string> = {
  ibkr: "#10b981", // emerald
  cpf: "#3b82f6", // blue
  endowus: "#f59e0b", // amber
};

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

function Card({ children }: { children: React.ReactNode }) {
  return (
    <div className="rounded-xl border border-slate-200 bg-white px-5 py-4 shadow-sm dark:border-slate-700 dark:bg-slate-900">
      {children}
    </div>
  );
}

function HistoryChart({ currency }: { currency: string }) {
  const { selected } = useScope();
  const { data } = useQuery({
    queryKey: ["networth", "history", selected, currency],
    queryFn: () =>
      getJSON<NetWorthHistoryResponse>(
        `/api/networth/history?owner=${encodeURIComponent(selected)}&target=${currency}&months=36`,
      ),
  });

  const series = data?.series ?? [];
  if (series.length === 0) {
    return <p className="text-sm text-slate-400 dark:text-slate-500">No history yet.</p>;
  }

  return (
    <Card>
      <h2 className="mb-3 text-sm font-semibold text-slate-700 dark:text-slate-200">
        Net worth over time · {currency}
      </h2>
      <div className="h-72 w-full">
        <ResponsiveContainer width="100%" height="100%">
          <AreaChart data={series} margin={{ top: 4, right: 8, bottom: 0, left: 8 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="currentColor" className="text-slate-200 dark:text-slate-700" />
            <XAxis dataKey="month" tickFormatter={fmtMonth} tick={{ fontSize: 11 }} minTickGap={24} />
            <YAxis
              tick={{ fontSize: 11 }}
              width={70}
              tickFormatter={(v) => `${Math.round(v / 1000)}k`}
            />
            <Tooltip
              formatter={(v, name) => [
                fmtCode(Number(v), currency),
                SOURCE_LABEL[String(name)] ?? String(name),
              ]}
              labelFormatter={(l) => fmtMonth(String(l))}
            />
            {(["ibkr", "cpf", "endowus"] as const).map((k) => (
              <Area
                key={k}
                type="monotone"
                dataKey={k}
                stackId="1"
                stroke={SOURCE_COLORS[k]}
                fill={SOURCE_COLORS[k]}
                fillOpacity={0.25}
              />
            ))}
          </AreaChart>
        </ResponsiveContainer>
      </div>
    </Card>
  );
}

function BreakdownCard({ kind, src, currency }: { kind: string; src: NetWorthSource; currency: string }) {
  const entries = Object.entries(src.breakdown ?? {});
  return (
    <Card>
      <div className="flex items-baseline justify-between">
        <h3 className="text-sm font-semibold text-slate-700 dark:text-slate-200">
          {SOURCE_LABEL[kind] ?? kind}
        </h3>
        <span className="text-lg font-bold text-slate-900 dark:text-slate-50">
          {fmtCode(src.converted, currency)}
        </span>
      </div>
      {entries.length > 0 && (
        <div className="mt-2 divide-y divide-slate-100 dark:divide-slate-800">
          {entries.map(([cat, val]) => (
            <div key={cat} className="flex justify-between py-1 text-sm">
              <span className="text-slate-500 dark:text-slate-400">{cat}</span>
              <span className="font-medium text-slate-700 dark:text-slate-200">
                {fmtCode(val, src.currency)}
              </span>
            </div>
          ))}
        </div>
      )}
      {src.as_of && (
        <p className="mt-2 text-xs text-slate-400 dark:text-slate-500">
          as of {new Date(src.as_of).toLocaleDateString()}
        </p>
      )}
    </Card>
  );
}

function HoldingsTable({ currency }: { currency: string }) {
  const { selected } = useScope();
  const { data } = useQuery({
    queryKey: ["holdings", selected, currency],
    queryFn: () =>
      getJSON<HoldingsResponse>(
        `/api/holdings?owner=${encodeURIComponent(selected)}&target=${currency}`,
      ),
  });
  const rows = data?.holdings ?? [];
  if (rows.length === 0) return null;

  return (
    <Card>
      <h2 className="mb-3 text-sm font-semibold text-slate-700 dark:text-slate-200">
        Endowus holdings
      </h2>
      <div className="overflow-x-auto">
        <table className="min-w-full text-sm">
          <thead className="text-left text-xs uppercase tracking-wide text-slate-400 dark:text-slate-500">
            <tr>
              <th className="py-2 pr-4">Fund</th>
              <th className="py-2 pr-4">Asset class</th>
              <th className="py-2 pr-4">Funding</th>
              <th className="py-2 pr-4 text-right">Value</th>
              <th className="py-2 text-right">Alloc</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100 dark:divide-slate-800">
            {rows.map((h, i) => (
              <tr key={i} className="text-slate-700 dark:text-slate-200">
                <td className="py-2 pr-4 font-medium">{h.fund_name}</td>
                <td className="py-2 pr-4 text-slate-500 dark:text-slate-400">{h.asset_class ?? "—"}</td>
                <td className="py-2 pr-4 text-slate-500 dark:text-slate-400">{h.funding_source ?? "—"}</td>
                <td className="py-2 pr-4 text-right">{fmtCode(h.market_value, h.currency)}</td>
                <td className="py-2 text-right text-slate-500 dark:text-slate-400">
                  {h.allocation_pct != null ? `${h.allocation_pct}%` : "—"}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </Card>
  );
}

export function NetWorthPage() {
  const { selected } = useScope();
  const { currency } = useDisplayCurrency();

  const { data } = useQuery({
    queryKey: ["networth", selected, currency],
    queryFn: () =>
      getJSON<NetWorthResponse>(
        `/api/networth?owner=${encodeURIComponent(selected)}&target=${currency}`,
      ),
  });

  // Per-source breakdown cards, aggregated across the owners in scope.
  const bySource: Record<string, NetWorthSource> = {};
  for (const owner of data?.owners ?? []) {
    for (const [kind, src] of Object.entries(owner.sources)) {
      const existing = bySource[kind];
      if (!existing) {
        bySource[kind] = { ...src, breakdown: { ...(src.breakdown ?? {}) } };
      } else {
        existing.converted = (existing.converted ?? 0) + (src.converted ?? 0);
        for (const [c, v] of Object.entries(src.breakdown ?? {})) {
          existing.breakdown = existing.breakdown ?? {};
          existing.breakdown[c] = (existing.breakdown[c] ?? 0) + v;
        }
      }
    }
  }

  return (
    <div className="space-y-6">
      <HistoryChart currency={currency} />

      <div className="grid gap-4 sm:grid-cols-3">
        {Object.entries(bySource).map(([kind, src]) => (
          <BreakdownCard key={kind} kind={kind} src={src} currency={currency} />
        ))}
      </div>

      <HoldingsTable currency={currency} />

      <p className="text-xs text-slate-400 dark:text-slate-500">
        Combined figures convert each source into {currency} at the current FX
        rate; statement sources show the date of their latest upload.
      </p>
    </div>
  );
}
