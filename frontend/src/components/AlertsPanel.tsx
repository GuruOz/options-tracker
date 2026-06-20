import { useQuery } from "@tanstack/react-query";
import { getJSON } from "../api/client";
import type { Position } from "../api/types";

function AlertItem({ position }: { position: Position }) {
  let icon = "ℹ️";
  let color = "bg-slate-100 border-slate-200 text-slate-800 dark:bg-slate-800 dark:border-slate-700 dark:text-slate-200";
  let title = "Alert";
  let message = "";

  if (position.status === "TAKE PROFIT") {
    icon = "🎯";
    color = "bg-emerald-50 border-emerald-200 text-emerald-900 dark:bg-emerald-950/30 dark:border-emerald-800/50 dark:text-emerald-100";
    title = "Take Profit";
    message = `You have captured ${(position.premium_captured_pct! * 100).toFixed(1)}% of the premium. Consider closing to secure profit.`;
  } else if (position.status === "AT RISK") {
    icon = "⚠️";
    color = "bg-red-50 border-red-200 text-red-900 dark:bg-red-950/30 dark:border-red-800/50 dark:text-red-100";
    title = "At Risk";
    message = `Cushion is dangerously low (${(position.cushion_pct! * 100).toFixed(1)}%). The underlying is approaching the strike.`;
  } else if (position.status === "EXPIRING") {
    icon = "⏳";
    color = "bg-amber-50 border-amber-200 text-amber-900 dark:bg-amber-950/30 dark:border-amber-800/50 dark:text-amber-100";
    title = "Expiring Soon";
    message = `Only ${position.dte} days to expiration. Consider rolling or closing.`;
  }

  return (
    <div className={`flex items-start gap-3 rounded-lg border p-3 ${color}`}>
      <div className="text-xl leading-none">{icon}</div>
      <div className="flex-1">
        <div className="flex items-baseline justify-between">
          <h3 className="font-semibold text-sm">
            {position.symbol} {position.sec_type} {position.strike}{position.right} <span className="opacity-75 font-normal ml-1">({title})</span>
          </h3>
          <span className="text-xs font-medium opacity-75">
            Mark: {position.mark?.toFixed(2)}
          </span>
        </div>
        <p className="mt-1 text-xs opacity-90">{message}</p>
      </div>
    </div>
  );
}

export function AlertsPanel() {
  const { data } = useQuery({
    queryKey: ["alerts"],
    queryFn: () => getJSON<Position[]>("/api/alerts"),
  });

  const alerts = data ?? [];

  if (alerts.length === 0) {
    return null; // Hide panel completely if there are no alerts to keep UI clean
  }

  return (
    <section className="mb-6 rounded-xl border border-rose-200 bg-white p-5 shadow-sm dark:border-rose-900/50 dark:bg-slate-900">
      <h2 className="mb-4 flex items-center gap-2 text-base font-semibold text-slate-800 dark:text-slate-100">
        <span className="text-rose-500">🚨</span> Action Required
        <span className="rounded-full bg-rose-100 px-2 py-0.5 text-xs font-bold text-rose-600 dark:bg-rose-900/30 dark:text-rose-400">
          {alerts.length}
        </span>
      </h2>
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
        {alerts.map((p) => (
          <AlertItem key={p.conid} position={p} />
        ))}
      </div>
    </section>
  );
}
