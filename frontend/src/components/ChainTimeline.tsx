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
export const isAssignedOpenChain = (c: RollChain) => {
  if (c.status !== "open") return false;
  let stockPos = 0;
  let hasAssignment = false;
  for (const l of c.legs ?? []) {
    if (l.role === "assignment" || l.role === "assignment_stock") {
      hasAssignment = true;
    }
    if (l.role === "assignment_stock" || l.role === "stock_close") {
      const dir = l.action === "B" ? 1 : l.action === "S" ? -1 : 0;
      stockPos += dir * (l.qty || 0);
    }
  }
  return hasAssignment && Math.abs(stockPos) > 0.1;
};

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

// Headline credit for a chain. While a chain is open, the premium on its open leg
// is locked — a roll only banks the decay on the leg it replaced — so an open
// chain reports what it has banked, and a closed one its final total.
// `banked_credit` is absent on rows written before the cycle fields existed;
// falling back to the total keeps those readable until the next rebuild.
export const chainHeadline = (c: RollChain) => {
  const open = c.status === "open";
  const banked = open ? c.banked_credit ?? c.cumulative_credit : c.cumulative_credit;
  // Roll-to-the-end view: credit gathered beyond the opening sale, which lands in
  // full only if the open leg expires worthless. Best-case, not banked — an early
  // assignment or a buyback above the credit claws it back. Hidden for a cycle
  // that hasn't rolled yet (cumulative == opener) — it would always read 0.
  const opener = open ? c.initial_credit : null;
  const beyondOpener =
    opener != null && c.cumulative_credit != null && Math.abs(c.cumulative_credit - opener) >= 0.5
      ? c.cumulative_credit - opener
      : null;
  return {
    value: banked,
    label: open ? "banked to date" : "net total",
    locked: open ? c.open_credit ?? 0 : 0,
    ifWorthless: c.cumulative_credit,
    opener,
    beyondOpener,
  };
};

export function ChainTimeline({ chain, onClose }: { chain: RollChain | null; onClose: () => void }) {
  if (!chain) return null;

  const legs = chain.legs ?? [];
  // Running net so each row shows the cumulative credit after that event.
  let running = 0;
  const rows = legs.map((leg) => {
    running += leg.credit ?? 0;
    return { leg, running };
  });

  const headline = chainHeadline(chain);
  const net = headline.value;

  // Equal-priority stat band under the header. The locked open-leg premium is
  // deliberately not shown — the user reads the chain through banked credit,
  // decay gathered by rolling, and the total the cycle is working toward.
  type StatTile = { key: string; label: string; value: number | null; sub: string; tip?: string; signed?: boolean };
  const tiles: StatTile[] = [
    {
      key: "banked",
      label: headline.label,
      value: net,
      sub: chain.status === "open" ? "realised so far" : "final result",
    },
  ];
  if (headline.locked !== 0 && headline.beyondOpener != null) {
    tiles.push({
      key: "decay",
      label: "Realised time decay",
      value: headline.beyondOpener,
      sub: `beyond the ${money(headline.opener)} opener`,
      signed: true,
      tip: "Roll-to-the-end view: total chain credit over the opening sale this cycle is working toward. Best case, not banked — it lands only if the open leg expires worthless; an early assignment or a buyback above the credit reduces it.",
    });
  }
  if (headline.locked !== 0) {
    tiles.push({
      key: "total",
      label: "Time decay + initial premium",
      value: headline.ifWorthless,
      sub: "when chain closes",
      tip: "Rolling doesn't collect the new put's premium — it swaps one open leg for another. Only the decay on the leg you closed is banked; the open leg pays out when it expires worthless or you buy it back.",
    });
  }
  const tileCols = ["grid-cols-1", "grid-cols-2", "grid-cols-3"][tiles.length - 1];

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4"
      onClick={onClose}
    >
      <div
        className="max-h-[85vh] w-full max-w-2xl overflow-y-auto rounded-xl border border-slate-200 bg-white p-6 shadow-xl dark:border-slate-700 dark:bg-slate-900"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="mb-4">
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
        </div>

        <div className={`mb-5 grid gap-2 ${tileCols}`}>
          {tiles.map((t) => (
            <div
              key={t.key}
              title={t.tip}
              className="rounded-lg border border-slate-200 bg-slate-50 px-3 py-2 dark:border-slate-700 dark:bg-slate-800/40"
            >
              <div className="text-[11px] uppercase tracking-wide text-slate-400">{t.label}</div>
              <div
                className={`mt-0.5 text-xl font-bold tabular-nums ${
                  (t.value ?? 0) >= 0 ? "text-emerald-600 dark:text-emerald-400" : "text-red-600 dark:text-red-400"
                }`}
              >
                {t.signed && (t.value ?? 0) > 0 ? "+" : ""}
                {money(t.value)}
              </div>
              <div className="text-[11px] text-slate-400 dark:text-slate-500">{t.sub}</div>
            </div>
          ))}
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
