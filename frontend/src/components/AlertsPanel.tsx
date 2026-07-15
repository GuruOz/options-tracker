import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { getJSON } from "../api/client";
import type { Position, RollChain } from "../api/types";
import { ChainTimeline, chainLabel, money, isAssignedOpenChain } from "./ChainTimeline";

function AssignmentAlert({ chain, onOpen }: { chain: RollChain; onOpen: () => void }) {
  const stockLeg = (chain.legs ?? []).find((l) => l.role === "assignment_stock");
  const optLeg = (chain.legs ?? []).find((l) => l.role === "assignment");
  const shares = stockLeg?.qty ?? null;
  const strike = chain.strike ?? stockLeg?.strike ?? null;
  const when = optLeg?.date ?? stockLeg?.date ?? null;
  const right = (chain.right ?? "P").toUpperCase();
  const verb = right === "P" ? "now hold" : "had called away";

  return (
    <button
      onClick={onOpen}
      className="flex w-full items-start gap-3 rounded-lg border border-rose-200 bg-rose-50 p-3 text-left transition-colors hover:bg-rose-100 dark:border-rose-800/50 dark:bg-rose-950/30 dark:hover:bg-rose-950/50"
    >
      <div className="text-xl leading-none">⚠️</div>
      <div className="flex-1">
        <div className="flex items-baseline justify-between">
          <h3 className="text-sm font-semibold text-rose-900 dark:text-rose-100">
            {chainLabel(chain)} <span className="ml-1 font-normal opacity-75">(Assigned)</span>
          </h3>
          <span className="text-xs font-medium text-rose-700/75 dark:text-rose-300/75">View timeline →</span>
        </div>
        <p className="mt-1 text-xs text-rose-900/90 dark:text-rose-100/90">
          You {verb} {shares != null ? shares : ""} {chain.underlying_symbol ?? ""} shares
          {strike != null ? ` @ $${strike}` : ""} — short {right === "P" ? "put" : "call"} exercised against you
          {when ? ` on ${new Date(when).toLocaleDateString()}` : ""}. Decide whether to hold, sell, or write covered calls.
        </p>
      </div>
    </button>
  );
}

function AlertItem({ position }: { position: Position }) {
  let icon = "ℹ️";
  let color = "bg-slate-100 border-slate-200 text-slate-800 dark:bg-slate-800 dark:border-slate-700 dark:text-slate-200";
  let title = "Alert";
  let message = "";

  if (position.status === "TAKE PROFIT") {
    icon = "🎯";
    color = "bg-emerald-50 border-emerald-200 text-emerald-900 dark:bg-emerald-950/30 dark:border-emerald-800/50 dark:text-emerald-100";
    title = "Take Profit";
    // For a rolled position, say what unwinding the chain actually banks — the
    // current leg's own capture % is not the number worth acting on.
    message =
      position.chain_captured_pct != null
        ? `Closing this chain now banks ${money(position.chain_profit_if_closed)} of the ${money(
            position.chain_initial_credit
          )} premium it's working toward — ${(position.chain_captured_pct * 100).toFixed(1)}% captured.`
        : `You have captured ${(position.premium_captured_pct! * 100).toFixed(1)}% of the premium. Consider closing to secure profit.`;
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
  } else if (position.status === "WATCH") {
    icon = "👀";
    color = "bg-yellow-50 border-yellow-200 text-yellow-900 dark:bg-yellow-950/30 dark:border-yellow-800/50 dark:text-yellow-100";
    title = "Watch";
    const bits: string[] = [];
    const captured = position.chain_captured_pct ?? position.premium_captured_pct;
    if (captured != null && captured >= 0.65)
      bits.push(
        `${(captured * 100).toFixed(0)}% premium captured${position.chain_captured_pct != null ? " across the chain" : ""}`
      );
    if (position.cushion_pct != null && position.cushion_pct < 0.05)
      bits.push(`cushion ${(position.cushion_pct * 100).toFixed(1)}%`);
    message = `Approaching a threshold${bits.length ? ` — ${bits.join(", ")}` : ""}. Worth keeping an eye on.`;
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
  const [timelineChain, setTimelineChain] = useState<RollChain | null>(null);

  const { data } = useQuery({
    queryKey: ["alerts"],
    queryFn: () => getJSON<Position[]>("/api/alerts"),
  });
  const { data: chains } = useQuery({
    queryKey: ["chains"],
    queryFn: () => getJSON<RollChain[]>("/api/chains?status=open"),
  });

  const alerts = data ?? [];
  // Chains holding stock from an assignment surface as their own alert until the
  // shares are sold (the chain closes) — that's the correct "action" lifetime.
  const assigned = (chains ?? []).filter(isAssignedOpenChain);
  
  const assignedChainIds = new Set(assigned.map((c) => c.chain_id));
  const standaloneAlerts = alerts.filter((p) => p.chain_id == null || !assignedChainIds.has(p.chain_id));
  
  const count = standaloneAlerts.length + assigned.length;

  if (count === 0) {
    return null; // Hide panel completely if there are no alerts to keep UI clean
  }

  return (
    <section className="mb-6 rounded-xl border border-rose-200 bg-white p-5 shadow-sm dark:border-rose-900/50 dark:bg-slate-900">
      <h2 className="mb-4 flex items-center gap-2 text-base font-semibold text-slate-800 dark:text-slate-100">
        <span className="text-rose-500">🚨</span> Action Required
        <span className="rounded-full bg-rose-100 px-2 py-0.5 text-xs font-bold text-rose-600 dark:bg-rose-900/30 dark:text-rose-400">
          {count}
        </span>
      </h2>
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
        {assigned.map((c) => (
          <AssignmentAlert key={c.chain_id} chain={c} onOpen={() => setTimelineChain(c)} />
        ))}
        {standaloneAlerts.map((p) => (
          <AlertItem key={p.conid} position={p} />
        ))}
      </div>

      <ChainTimeline chain={timelineChain} onClose={() => setTimelineChain(null)} />
    </section>
  );
}
