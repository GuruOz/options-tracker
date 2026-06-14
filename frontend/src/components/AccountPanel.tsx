import { useQuery } from "@tanstack/react-query";
import { getJSON } from "../api/client";
import type { AccountSummary } from "../api/types";

const money = (v: number | null | undefined) =>
  v == null
    ? "—"
    : v.toLocaleString(undefined, {
        style: "currency",
        currency: "USD",
        maximumFractionDigits: 0,
      });

const STATS: { label: string; key: keyof AccountSummary }[] = [
  { label: "Net liquidation", key: "net_liquidation" },
  { label: "Available funds", key: "available_funds" },
  { label: "Excess liquidity", key: "excess_liquidity" },
  { label: "Maint. margin", key: "maintenance_margin" },
  { label: "Cash", key: "cash" },
];

export function AccountPanel() {
  const { data } = useQuery({
    queryKey: ["account"],
    queryFn: () => getJSON<AccountSummary | null>("/api/account"),
  });

  return (
    <section className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm">
      <h2 className="mb-3 text-base font-semibold text-slate-800">Account</h2>
      <div className="grid grid-cols-2 gap-4 sm:grid-cols-3 lg:grid-cols-5">
        {STATS.map((s) => (
          <div key={s.key}>
            <p className="text-xs uppercase tracking-wide text-slate-400">{s.label}</p>
            <p className="mt-1 text-lg font-semibold text-slate-800">
              {money(data?.[s.key] as number | null)}
            </p>
          </div>
        ))}
      </div>
    </section>
  );
}
