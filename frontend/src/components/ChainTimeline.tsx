import type { RollChain, RollChainLeg } from "../api/types";

export const money = (v: number | null) =>
  v == null ? "—" : v.toLocaleString(undefined, { maximumFractionDigits: 0 });

// "NVDA 216P" from the chain's underlying, strike and right; "NVDA 216→210P"
// when a chain spans strikes (a manually-linked cross-strike roll). String(216)
// -> "216" and String(217.5) -> "217.5", so no trailing-zero formatting needed.
export const chainLabel = (c: RollChain) => {
  const sym = c.underlying_symbol ?? "—";
  const right = c.right ?? "";

  const openStrikes = (c.legs ?? [])
    .filter((l) => l.role === "open" && l.strike != null)
    .map((l) => l.strike as number);
  const first = openStrikes.length ? openStrikes[0] : c.strike;
  const last = openStrikes.length ? openStrikes[openStrikes.length - 1] : c.strike;

  if (first == null) return right ? `${sym} ${right}` : sym;
  const strikeText = last != null && last !== first ? `${first}→${last}` : `${first}`;
  return `${sym} ${strikeText}${right}`;
};

// A chain that holds shares from an assignment and hasn't been sold out yet —
// i.e. the user was put the stock and still owns it. Used to raise the alert.
export const isAssignedOpenChain = (c: RollChain) =>
  c.status === "open" &&
  (c.legs ?? []).some((l) => l.role === "assignment" || l.role === "assignment_stock");

// Each leg role gets an icon, a human label and a color so the timeline reads as
// a story rather than a table. Mirrors the leg roles produced by rolls.py.
type RolePresentation = { icon: string; label: (l: RollChainLeg) => string; color: string };

const ROLE: Record<string, RolePresentation> = {
  open: { icon: "🟢", label: () => "Sold to open", color: "text-emerald-600 dark:text-emerald-400" },
  roll: { icon: "🔄", label: () => "Rolled", color: "text-sky-600 dark:text-sky-400" },
  close: { icon: "⚪", label: () => "Bought to close", color: "text-slate-500 dark:text-slate-400" },
  expired: { icon: "💨", label: () => "Expired worthless", color: "text-slate-500 dark:text-slate-400" },
  assignment: { icon: "⚠️", label: () => "Assigned — put exercised against you", color: "text-rose-600 dark:text-rose-400" },
  assignment_stock: {
    icon: "📦",
    label: (l) => `Received ${l.qty != null ? l.qty : ""} shares @ $${l.strike ?? "—"}`.replace("  ", " "),
    color: "text-amber-600 dark:text-amber-400",
  },
  stock_close: { icon: "💵", label: () => "Sold shares", color: "text-emerald-600 dark:text-emerald-400" },
};

const fmtDate = (d: string | null) =>
  d ? new Date(d).toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" }) : "—";

const fmtExpiry = (d: string | null) =>
  d ? new Date(d + "T00:00:00").toLocaleDateString(undefined,
      { month: "short", day: "numeric", year: "2-digit" }) : null;

const STOCK_ROLES = new Set(["assignment_stock", "stock_close"]);

export function ChainTimeline({ chain, onClose }: { chain: RollChain | null; onClose: () => void }) {
  if (!chain) return null;

  const legs = chain.legs ?? [];
  // Running net so each row shows the cumulative credit after that event.
  let running = 0;
  const rows = legs.map((leg) => {
    running += leg.credit ?? 0;
    return { leg, running };
  });

  const net = chain.cumulative_credit;

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4"
      onClick={onClose}
    >
      <div
        className="max-h-[85vh] w-full max-w-2xl overflow-y-auto rounded-xl border border-slate-200 bg-white p-6 shadow-xl dark:border-slate-700 dark:bg-slate-900"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="mb-5 flex items-start justify-between">
          <div>
            <h2 className="flex items-center gap-2 text-lg font-semibold text-slate-800 dark:text-slate-100">
              🔗 {chainLabel(chain)}
              <span
                className={`rounded-full px-2 py-0.5 text-[10px] font-medium uppercase tracking-wide ${
                  chain.status === "open"
                    ? "bg-emerald-100 text-emerald-700 dark:bg-emerald-900/30 dark:text-emerald-400"
                    : "bg-slate-200 text-slate-600 dark:bg-slate-700 dark:text-slate-300"
                }`}
              >
                {chain.status}
                {chain.close_reason ? ` · ${chain.close_reason.replace(/_/g, " ")}` : ""}
              </span>
            </h2>
            <p className="mt-1 text-xs text-slate-500 dark:text-slate-400">
              Opened {chain.opened_at ? new Date(chain.opened_at).toLocaleDateString() : "—"}
              {chain.closed_at ? ` · Closed ${new Date(chain.closed_at).toLocaleDateString()}` : ""}
            </p>
          </div>
          <div className="text-right">
            <div
              className={`text-xl font-bold tabular-nums ${
                (net ?? 0) >= 0 ? "text-emerald-600 dark:text-emerald-400" : "text-red-600 dark:text-red-400"
              }`}
            >
              {money(net)}
            </div>
            <div className="text-[10px] uppercase tracking-wide text-slate-400">net to date</div>
          </div>
        </div>

        <ol className="relative ml-3 border-l border-slate-200 dark:border-slate-700">
          {rows.map(({ leg, running }) => {
            const p = ROLE[leg.role] ?? { icon: "•", label: () => leg.role, color: "text-slate-500" };
            return (
              <li key={leg.leg_id} className="mb-5 ml-5">
                <span className="absolute -left-3 flex h-6 w-6 items-center justify-center rounded-full bg-white text-sm ring-4 ring-white dark:bg-slate-900 dark:ring-slate-900">
                  {p.icon}
                </span>
                <div className="flex items-baseline justify-between gap-3">
                  <span className={`text-sm font-medium ${p.color}`}>{p.label(leg)}</span>
                  <span className="whitespace-nowrap text-[11px] text-slate-400">{fmtDate(leg.date)}</span>
                </div>
                <div className="mt-0.5 flex items-center justify-between gap-3 text-xs text-slate-500 dark:text-slate-400">
                  <span>
                    {!STOCK_ROLES.has(leg.role) && leg.strike != null && (
                      <span className="mr-2 font-mono text-slate-700 dark:text-slate-300">
                        {leg.strike}{chain.right ?? ""}
                        {fmtExpiry(leg.expiry) && (
                          <span className="ml-1 font-sans text-slate-400 dark:text-slate-500">
                            · exp {fmtExpiry(leg.expiry)}
                          </span>
                        )}
                      </span>
                    )}
                    {leg.action ? `${leg.action === "S" ? "Sell" : leg.action === "B" ? "Buy" : leg.action} ` : ""}
                    {leg.qty != null ? `${leg.qty} ` : ""}
                    {leg.price ? `@ ${leg.price.toFixed(2)}` : ""}
                  </span>
                  <span className="flex items-center gap-3 tabular-nums">
                    <span className={leg.credit >= 0 ? "text-emerald-600 dark:text-emerald-400" : "text-red-600 dark:text-red-400"}>
                      {money(leg.credit)}
                    </span>
                    <span className="text-slate-400">Σ {money(running)}</span>
                  </span>
                </div>
              </li>
            );
          })}
        </ol>

        <div className="mt-4 flex justify-end">
          <button
            onClick={onClose}
            className="rounded-lg bg-slate-100 px-4 py-1.5 text-sm font-medium text-slate-600 transition-colors hover:bg-slate-200 dark:bg-slate-800 dark:text-slate-300 dark:hover:bg-slate-700"
          >
            Close
          </button>
        </div>
      </div>
    </div>
  );
}
