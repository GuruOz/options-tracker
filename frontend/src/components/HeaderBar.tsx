import { useQuery } from "@tanstack/react-query";
import { getJSON } from "../api/client";
import type { AccountSummary, SessionState } from "../api/types";

const money = (v: number | null | undefined) =>
  v == null
    ? "—"
    : v.toLocaleString(undefined, {
        style: "currency",
        currency: "USD",
        maximumFractionDigits: 0,
      });

const STATUS_DOT: Record<string, string> = {
  authenticated: "bg-emerald-500",
  polling: "bg-emerald-500",
  disconnected: "bg-amber-400",
  unknown: "bg-slate-400",
};

const STATUS_TEXT: Record<string, string> = {
  authenticated: "text-emerald-700",
  polling: "text-emerald-700",
  disconnected: "text-amber-700",
  unknown: "text-slate-500",
};

const STATS: { label: string; key: keyof AccountSummary }[] = [
  { label: "Net liq.", key: "net_liquidation" },
  { label: "Available", key: "available_funds" },
  { label: "Excess liq.", key: "excess_liquidity" },
  { label: "Maint. margin", key: "maintenance_margin" },
  { label: "Cash", key: "cash" },
];

export function HeaderBar({ session }: { session: SessionState }) {
  const { data: account } = useQuery({
    queryKey: ["account"],
    queryFn: () => getJSON<AccountSummary | null>("/api/account"),
  });

  const dotClass = STATUS_DOT[session.status] ?? STATUS_DOT.unknown;
  const textClass = STATUS_TEXT[session.status] ?? STATUS_TEXT.unknown;
  const checked = session.last_checked
    ? new Date(session.last_checked).toLocaleTimeString()
    : "—";

  return (
    <div className="rounded-xl border border-slate-200 bg-white px-5 py-4 shadow-sm">
      <div className="flex flex-wrap items-center gap-x-6 gap-y-3">
        {/* Connection status */}
        <div className="flex items-center gap-2 min-w-[160px]">
          <span className={`h-2.5 w-2.5 rounded-full shrink-0 ${dotClass}`} aria-hidden />
          <div>
            <p className={`text-sm font-semibold ${textClass}`}>{session.message}</p>
            <p className="text-xs text-slate-400">
              {session.account_id ? `${session.account_id} · ` : ""}
              checked {checked}
            </p>
          </div>
        </div>

        {/* Divider */}
        <div className="hidden h-8 w-px bg-slate-200 sm:block" aria-hidden />

        {/* Account stats */}
        <div className="flex flex-wrap gap-x-6 gap-y-2">
          {STATS.map((s) => (
            <div key={s.key}>
              <p className="text-xs uppercase tracking-wide text-slate-400">{s.label}</p>
              <p className="mt-0.5 text-sm font-semibold text-slate-800">
                {money(account?.[s.key] as number | null)}
              </p>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
