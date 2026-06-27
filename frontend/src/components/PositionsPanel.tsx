import { useEffect, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { getJSON } from "../api/client";
import type { Position, RollChain, Trade } from "../api/types";
// `chainLabel` ("NVDA 216P") and `money` live in ./ChainTimeline so the timeline
// and alerts panel can share the same formatting.
import { ChainTimeline, money, chainLabel } from "./ChainTimeline";

const num = (v: number | null, d = 2) => (v == null ? "—" : v.toFixed(d));
const percent = (v: number | null) => (v == null ? "—" : `${(v * 100).toFixed(1)}%`);

function StatusPill({ status }: { status: string | null }) {
  if (!status) return <span className="text-slate-400">—</span>;
  let color = "bg-slate-100 text-slate-600 dark:bg-slate-800 dark:text-slate-400";
  if (status === "TAKE PROFIT") color = "bg-emerald-100 text-emerald-700 dark:bg-emerald-900/30 dark:text-emerald-400";
  else if (status === "AT RISK") color = "bg-red-100 text-red-700 dark:bg-red-900/30 dark:text-red-400";
  else if (status === "EXPIRING") color = "bg-amber-100 text-amber-700 dark:bg-amber-900/30 dark:text-amber-400";
  else if (status === "WATCH") color = "bg-yellow-100 text-yellow-700 dark:bg-yellow-900/30 dark:text-yellow-400";
  return <span className={`px-2 py-0.5 rounded-full text-[10px] font-medium tracking-wide ${color}`}>{status}</span>;
}

export function PositionsPanel({
  selectedConid,
  onSelect,
}: {
  selectedConid: number | null;
  onSelect: (conid: number) => void;
}) {
  const [showClosed, setShowClosed] = useState(false);
  const [showTrades, setShowTrades] = useState(false);
  const [uploadMsg, setUploadMsg] = useState("");
  const [timelineChain, setTimelineChain] = useState<RollChain | null>(null);
  const queryClient = useQueryClient();

  const { data: positions, isFetching: posFetching } = useQuery({
    queryKey: ["positions"],
    queryFn: () => getJSON<Position[]>("/api/positions"),
  });
  const { data: chains } = useQuery({
    queryKey: ["chains"],
    queryFn: () => getJSON<RollChain[]>("/api/chains?status=open"),
  });
  const { data: closedChains, isFetching: closedLoading } = useQuery({
    queryKey: ["chains", "closed"],
    queryFn: () => getJSON<RollChain[]>("/api/chains?status=closed"),
    enabled: showClosed,
  });
  const { data: optionTrades } = useQuery({
    queryKey: ["trades", "options"],
    queryFn: () => getJSON<Trade[]>("/api/trades/options"),
  });

  const rows = positions ?? [];
  const chainMap = new Map<string, RollChain>();
  for (const c of chains ?? []) {
    chainMap.set(c.chain_id, c);
  }

  const grouped = new Map<string, Position[]>();
  const ungrouped: Position[] = [];
  for (const p of rows) {
    if (p.chain_id) {
      const arr = grouped.get(p.chain_id) ?? [];
      arr.push(p);
      grouped.set(p.chain_id, arr);
    } else {
      ungrouped.push(p);
    }
  }

  const chainEntries = Array.from(grouped.entries());
  const closedList = closedChains ?? [];

  // Default the decay panel to the first chartable position once data lands, so
  // the panel and the highlighted row stay in sync from the start.
  const firstChartable = rows.find((p) => (p.decay_curve?.length ?? 0) > 1)?.conid ?? null;
  useEffect(() => {
    if (selectedConid == null && firstChartable != null) onSelect(firstChartable);
  }, [selectedConid, firstChartable, onSelect]);

  return (
    <section className="overflow-x-auto rounded-xl border border-slate-200 bg-white p-5 shadow-sm dark:border-slate-700 dark:bg-slate-900">
      <h2 className="mb-3 flex items-center gap-3 text-base font-semibold text-slate-800 dark:text-slate-100">
        <span>
          Open positions{" "}
          <span className="text-sm font-normal text-slate-400 dark:text-slate-500">
            ({rows.length}{chainEntries.length > 0 ? ` · ${chainEntries.length} chain${chainEntries.length > 1 ? "s" : ""}` : ""})
          </span>
        </span>
        <button
          onClick={() => {
            queryClient.invalidateQueries({ queryKey: ["positions"] });
            queryClient.invalidateQueries({ queryKey: ["chains"] });
            queryClient.invalidateQueries({ queryKey: ["chains", "closed"] });
            queryClient.invalidateQueries({ queryKey: ["trades", "options"] });
            queryClient.invalidateQueries({ queryKey: ["alerts"] });
            queryClient.invalidateQueries({ queryKey: ["risk"] });
            queryClient.invalidateQueries({ queryKey: ["account"] });
          }}
          disabled={posFetching}
          className="rounded-lg bg-slate-100 px-2 py-1 text-[10px] font-medium text-slate-500 transition-colors hover:bg-slate-200 disabled:opacity-50 dark:bg-slate-800 dark:text-slate-400 dark:hover:bg-slate-700"
        >
          {posFetching ? "Refreshing…" : "Refresh"}
        </button>
      </h2>
      {rows.length === 0 ? (
        <p className="text-sm text-slate-500 dark:text-slate-400">
          No positions yet — or the first snapshot is still being polled.
        </p>
      ) : (
        <table className="w-full text-sm">
          <thead>
            <tr className="text-left text-xs uppercase tracking-wide text-slate-400 dark:text-slate-500 border-b border-slate-100 dark:border-slate-700">
              <th className="py-2 pr-3" title="Underlying ticker. 🔗 marks a position that belongs to a roll chain.">Symbol</th>
              <th className="pr-3" title="Security type, plus the option right (P/C) and strike.">Type</th>
              <th className="pr-3" title="Lifecycle pill: TAKE PROFIT (>=70% premium captured), AT RISK (cushion < 3%), EXPIRING (<=2 DTE), or WATCH (near a threshold: >=65% captured or cushion < 5%).">Status</th>
              <th className="pr-3 text-right" title="Days to expiration (calendar days until the contract expires).">DTE</th>
              <th className="pr-3 text-right" title="Signed contract quantity. Negative = short (sold).">Qty</th>
              <th className="pr-3 text-right" title="Current mark price of the option, per share.">Last</th>
              <th className="pr-3 text-right" title="Live spot price of the underlying stock/ETF. Only shown for tracked underlyings.">Spot</th>
              <th className="pr-3 text-right" title="Your average entry price per share (avg cost / 100).">My Avg</th>
              <th className="pr-3 text-right" title="In-the-money value: total $ across all contracts (per-share intrinsic x 100 x |qty|). Needs the spot price.">Intrinsic ($)</th>
              <th className="pr-3 text-right" title="Time value remaining: total $ across all contracts (mark - intrinsic, x 100 x |qty|). This is what decays to zero by expiry.">Extrinsic ($)</th>
              <th className="pr-3 text-right" title="Distance from spot to strike. Put: (spot - strike) / spot. Call: (strike - spot) / spot. Measures room before the strike - independent of P&L.">Cushion</th>
              <th className="pr-3 text-right" title="% of the premium you've captured so far: (credit received - cost to buy back) / credit received.">Captured</th>
              <th className="pr-3 text-right" title="Unrealized profit/loss on the position, in account currency.">Unreal P&amp;L</th>
              <th className="pr-3 text-right" title="Delta - per-share price sensitivity to a $1 move in the underlying.">Δ</th>
              <th className="text-right" title="Theta - estimated daily time decay, per share.">Θ</th>
            </tr>
          </thead>
          <tbody>
            {chainEntries.map(([chainId, chainPositions]) => {
              const chain = chainMap.get(chainId);
              return (
                <ChainGroup
                  key={chainId}
                  chainId={chainId}
                  chain={chain}
                  positions={chainPositions}
                  selectedConid={selectedConid}
                  onSelect={onSelect}
                  onOpenTimeline={setTimelineChain}
                />
              );
            })}
            {ungrouped.map((p) => (
              <PositionRow key={p.conid} p={p} selected={p.conid === selectedConid} onSelect={onSelect} />
            ))}
          </tbody>
        </table>
      )}

      {/* Closed chains (historical) */}
      <div className="mt-6 border-t border-slate-200 pt-4 dark:border-slate-700">
        <button
          onClick={() => setShowClosed(!showClosed)}
          className="flex items-center gap-2 text-sm font-medium text-slate-600 hover:text-slate-800 dark:text-slate-400 dark:hover:text-slate-200 transition-colors"
        >
          <span className={`transform transition-transform ${showClosed ? "rotate-90" : ""}`}>&#9654;</span>
          Closed chains
          <span className="text-xs font-normal text-slate-400">
            ({showClosed ? closedList.length : "..."})
          </span>
        </button>
        {showClosed && (
          <div className="mt-3">
            {closedLoading ? (
              <p className="text-xs text-slate-400">Loading...</p>
            ) : closedList.length === 0 ? (
              <p className="text-xs text-slate-400">No closed chains yet.</p>
            ) : (
              <table className="w-full text-sm">
                <thead>
                  <tr className="text-left text-xs uppercase tracking-wide text-slate-400 dark:text-slate-500 border-b border-slate-100 dark:border-slate-700">
                    <th className="py-2 pr-3">Symbol</th>
                    <th className="pr-3 text-right">Legs</th>
                    <th className="pr-3 text-right">Opened</th>
                    <th className="pr-3 text-right">Closed</th>
                    <th className="text-right">Cumulative credit</th>
                  </tr>
                </thead>
                <tbody>
                  {closedList.map((c) => (
                    <tr
                      key={c.chain_id}
                      className="cursor-pointer border-b border-slate-50 hover:bg-slate-50 dark:border-slate-800/50 dark:hover:bg-slate-800/50 last:border-0"
                      onClick={() => setTimelineChain(c)}
                      title="View chronological timeline"
                    >
                      <td className="py-2 pr-3 font-medium text-slate-700 dark:text-slate-300">📜 {chainLabel(c)}</td>
                      <td className="pr-3 text-right tabular-nums dark:text-slate-300">{c.leg_count}</td>
                      <td className="pr-3 text-right text-xs text-slate-400">{c.opened_at ? new Date(c.opened_at).toLocaleDateString() : "—"}</td>
                      <td className="pr-3 text-right text-xs text-slate-400">{c.closed_at ? new Date(c.closed_at).toLocaleDateString() : "—"}</td>
                      <td className={`text-right tabular-nums font-semibold ${(c.cumulative_credit ?? 0) >= 0 ? "text-emerald-600 dark:text-emerald-400" : "text-red-600 dark:text-red-400"}`}>
                        {money(c.cumulative_credit)}
                        {c.close_reason && (
                          <span className="ml-2 px-1.5 py-0.5 rounded-sm bg-slate-200 dark:bg-slate-700 text-[9px] uppercase tracking-wide text-slate-600 dark:text-slate-300">
                            {c.close_reason.replace("_", " ")}
                          </span>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>
        )}
      </div>

      {/* Option trades (all historical) */}
      <div className="mt-6 border-t border-slate-200 pt-4 dark:border-slate-700">
        <button
          onClick={() => setShowTrades(!showTrades)}
          className="flex items-center gap-2 text-sm font-medium text-slate-600 hover:text-slate-800 dark:text-slate-400 dark:hover:text-slate-200 transition-colors"
        >
          <span className={`transform transition-transform ${showTrades ? "rotate-90" : ""}`}>&#9654;</span>
          Option trades
          <span className="text-xs font-normal text-slate-400">
            ({(optionTrades ?? []).length} total)
          </span>
        </button>
        {showTrades && (
        <div className="mt-3">
        <div className="mb-3 flex items-center gap-3">
          <label className="cursor-pointer rounded-lg bg-blue-50 px-3 py-1.5 text-xs font-medium text-blue-700 transition-colors hover:bg-blue-100 dark:bg-blue-900/30 dark:text-blue-300 dark:hover:bg-blue-900/50">
            Import CSV
            <input
              type="file"
              accept=".csv"
              className="hidden"
              onChange={async (e) => {
                const file = e.target.files?.[0];
                if (!file) return;
                setUploadMsg("Uploading...");
                try {
                  const form = new FormData();
                  form.append("file", file);
                  const res = await fetch("/api/trades/upload", {
                    method: "POST",
                    body: form,
                  });
                  const json = await res.json();
                  setUploadMsg(json.message ?? json.status);
                  queryClient.invalidateQueries({ queryKey: ["trades", "options"] });
                  queryClient.invalidateQueries({ queryKey: ["chains"] });
                  queryClient.invalidateQueries({ queryKey: ["chains", "closed"] });
                } catch {
                  setUploadMsg("Upload failed.");
                }
                e.target.value = "";
              }}
            />
          </label>
          <span className="text-[10px] text-slate-400">Download Activity Statement CSV from IBKR Client Portal → Reports → Activity</span>
          {uploadMsg && <span className="text-[10px] font-medium text-slate-500">{uploadMsg}</span>}
        </div>
        {(optionTrades ?? []).length === 0 ? (
          <p className="text-xs text-slate-400 dark:text-slate-500">
            No option trades found. IBKR only returns ~7 days of trades via the API.
            Older history requires the Flex/CSV importer.
          </p>
        ) : (
          <div className="max-h-96 overflow-y-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-left text-xs uppercase tracking-wide text-slate-400 dark:text-slate-500 border-b border-slate-100 dark:border-slate-700 sticky top-0 bg-white dark:bg-slate-900">
                  <th className="py-2 pr-3">Date</th>
                  <th className="pr-3">Symbol</th>
                  <th className="pr-3">Side</th>
                  <th className="pr-3">Right</th>
                  <th className="pr-3 text-right">Strike</th>
                  <th className="pr-3">Expiry</th>
                  <th className="pr-3 text-right">Qty</th>
                  <th className="pr-3 text-right">Price</th>
                  <th className="pr-3 text-right">Comm</th>
                  <th className="text-right">Exec ID</th>
                </tr>
              </thead>
              <tbody>
                {optionTrades!.map((t) => (
                  <tr key={t.exec_id} className="border-b border-slate-50 dark:border-slate-800/50 last:border-0">
                    <td className="py-1.5 pr-3 text-xs text-slate-500 whitespace-nowrap">
                      {t.exec_time ? new Date(t.exec_time).toLocaleString() : "—"}
                    </td>
                    <td className="pr-3 font-medium text-slate-700 dark:text-slate-300">{t.symbol ?? "—"}</td>
                    <td className={`pr-3 text-xs font-semibold ${t.side === "S" ? "text-emerald-600 dark:text-emerald-400" : t.side === "A" ? "text-rose-600 dark:text-rose-400" : "text-red-600 dark:text-red-400"}`}>
                      {t.side === "S" ? "SELL" : t.side === "B" ? "BUY" : t.side === "A" ? "ASSIGN" : t.side ?? "—"}
                    </td>
                    <td className="pr-3 dark:text-slate-300">{t.right ?? "—"}</td>
                    <td className="pr-3 text-right tabular-nums dark:text-slate-300">{t.strike != null ? t.strike : "—"}</td>
                    <td className="pr-3 text-xs text-slate-500 whitespace-nowrap">
                      {t.expiry ? new Date(t.expiry).toLocaleDateString() : "—"}
                    </td>
                    <td className="pr-3 text-right tabular-nums dark:text-slate-300">{t.qty != null ? t.qty : "—"}</td>
                    <td className="pr-3 text-right tabular-nums dark:text-slate-300">{t.price != null ? t.price : "—"}</td>
                    <td className="pr-3 text-right tabular-nums text-slate-400">{t.commission != null ? t.commission.toFixed(2) : "—"}</td>
                    <td className="text-right font-mono text-[10px] text-slate-400">{t.exec_id}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        </div>
        )}
      </div>

      <ChainTimeline chain={timelineChain} onClose={() => setTimelineChain(null)} />
    </section>
  );
}

function ChainGroup({
  chainId,
  chain,
  positions,
  selectedConid,
  onSelect,
  onOpenTimeline,
}: {
  chainId: string;
  chain: RollChain | undefined;
  positions: Position[];
  selectedConid: number | null;
  onSelect: (conid: number) => void;
  onOpenTimeline: (chain: RollChain) => void;
}) {
  const [linking, setLinking] = useState(false);
  const queryClient = useQueryClient();
  const assigned = (chain?.legs ?? []).some(
    (l) => l.role === "assignment" || l.role === "assignment_stock",
  );

  const { data: allChains } = useQuery({
    queryKey: ["chains", "all"],
    queryFn: () => getJSON<RollChain[]>("/api/chains?status=all"),
    enabled: linking,
  });

  const handleClose = async (e: React.MouseEvent) => {
    e.stopPropagation();
    if (!confirm("Manually close this chain?")) return;
    await fetch(`/api/chains/${chainId}/close`, { method: "POST" });
    queryClient.invalidateQueries({ queryKey: ["positions"] });
    queryClient.invalidateQueries({ queryKey: ["chains"] });
    queryClient.invalidateQueries({ queryKey: ["chains", "closed"] });
  };

  const handleLink = async (execId: string) => {
    if (!execId) return;
    await fetch(`/api/chains/${chainId}/link`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ exec_id: execId }),
    });
    setLinking(false);
    queryClient.invalidateQueries({ queryKey: ["positions"] });
    queryClient.invalidateQueries({ queryKey: ["chains"] });
    queryClient.invalidateQueries({ queryKey: ["chains", "closed"] });
  };

  return (
    <>
      <tr
        className="bg-slate-50 dark:bg-slate-800/50 cursor-pointer hover:bg-slate-100 dark:hover:bg-slate-800 transition-colors border-t border-slate-200 dark:border-slate-700"
        onClick={() => chain && onOpenTimeline(chain)}
        title="View chronological timeline"
      >
        <td colSpan={15} className="py-2 px-2">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-3 text-xs">
              <span className="text-slate-400">📜</span>
              <span className="text-amber-600 dark:text-amber-400 font-semibold">🔗 Chain</span>
              {chain && (
                <span className="text-slate-600 dark:text-slate-300 font-bold tracking-wide">{chainLabel(chain)}</span>
              )}
              {assigned && (
                <span className="rounded-full bg-rose-100 px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-rose-700 dark:bg-rose-900/30 dark:text-rose-400">
                  ⚠️ Assigned
                </span>
              )}
              {chain?.cumulative_credit != null && (
                <span className={`font-semibold tabular-nums px-2 py-0.5 rounded-full ${chain.cumulative_credit >= 0 ? "bg-emerald-100/50 text-emerald-700 dark:bg-emerald-900/30 dark:text-emerald-400" : "bg-red-100/50 text-red-700 dark:bg-red-900/30 dark:text-red-400"}`}>
                  {money(chain.cumulative_credit)} net
                </span>
              )}
              <span className="text-slate-400 dark:text-slate-500">{chain?.legs?.length ?? positions.length} leg{(chain?.legs?.length ?? positions.length) !== 1 ? "s" : ""}</span>
            </div>
            <div onClick={(e) => e.stopPropagation()}>
              {linking ? (
                <div className="flex items-center gap-2">
                  <select
                    className="text-[10px] border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-900 rounded p-1 text-slate-700 dark:text-slate-300"
                    onChange={(e) => handleLink(e.target.value)}
                    defaultValue=""
                  >
                    <option value="" disabled>Select chain to merge...</option>
                    {(allChains ?? [])
                      .filter(c => c.chain_id !== chainId && c.underlying_symbol === chain?.underlying_symbol)
                      .map(c => {
                        const firstLeg = c.legs?.find(l => l.exec_id != null);
                        if (!firstLeg?.exec_id) return null;
                        const dateStr = c.opened_at ? new Date(c.opened_at).toLocaleDateString() : "";
                        return (
                          <option key={c.chain_id} value={firstLeg.exec_id}>
                            {chainLabel(c)} ({c.status}) {dateStr}
                          </option>
                        );
                      })}
                  </select>
                  <button onClick={() => setLinking(false)} className="px-2 py-1 text-[10px] font-medium text-slate-500 hover:text-slate-700 dark:hover:text-slate-300">
                    Cancel
                  </button>
                </div>
              ) : (
                <div className="flex items-center gap-2">
                  <button onClick={() => setLinking(true)} className="px-2 py-1 text-[10px] font-medium text-slate-500 bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-700 rounded hover:bg-slate-50 dark:hover:bg-slate-800 transition-colors">
                    Link cross-strike
                  </button>
                  <button onClick={handleClose} className="px-2 py-1 text-[10px] font-medium text-slate-500 bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-700 rounded hover:bg-slate-50 dark:hover:bg-slate-800 transition-colors">
                    Close chain
                  </button>
                </div>
              )}
            </div>
          </div>
        </td>
      </tr>
      {positions.map((p) => (
        <PositionRow key={p.conid} p={p} selected={p.conid === selectedConid} onSelect={onSelect} />
      ))}
    </>
  );
}

function PositionRow({ p, selected, onSelect }: { p: Position; selected: boolean; onSelect: (conid: number) => void }) {
  const myAvg = p.avg_cost != null ? p.avg_cost / 100 : null;
  const intrinsicMoney = p.intrinsic_value != null && p.position != null ? p.intrinsic_value * 100 * Math.abs(p.position) : null;
  const extrinsicMoney = p.extrinsic_value != null && p.position != null ? p.extrinsic_value * 100 * Math.abs(p.position) : null;
  const hasCurve = (p.decay_curve?.length ?? 0) > 1;

  return (
    <tr
      className={`border-b border-slate-50 dark:border-slate-800/50 last:border-0 transition-colors ${
        selected ? "bg-emerald-50 dark:bg-emerald-900/15" : "hover:bg-slate-50 dark:hover:bg-slate-800/50"
      } ${hasCurve ? "cursor-pointer" : ""}`}
      onClick={hasCurve ? () => onSelect(p.conid) : undefined}
      title={hasCurve ? "Chart time-value decay in the panel below" : undefined}
    >
      <td className="py-2 pr-3 font-medium text-slate-800 dark:text-slate-100">
        {hasCurve && (
          <svg
            viewBox="0 0 10 10"
            className={`mr-1.5 inline-block h-2.5 w-2.5 align-[-1px] ${selected ? "text-emerald-500" : "text-slate-300 dark:text-slate-600"}`}
            fill="none"
            stroke="currentColor"
            strokeWidth={1.5}
            strokeLinecap="round"
            strokeLinejoin="round"
          >
            <path d="M1 9 L3.5 5 L6 6.5 L9 1.5" />
          </svg>
        )}
        {p.symbol ?? "—"}
        {p.chain_id && <span className="ml-2 text-[10px] text-slate-400" title="Roll Chain">🔗</span>}
      </td>
      <td className="pr-3 dark:text-slate-300">
        {p.sec_type} {p.right ? ` ${p.right}` : ""} {p.strike ? p.strike : ""}
      </td>
      <td className="pr-3"><StatusPill status={p.status} /></td>
      <td className="pr-3 text-right tabular-nums dark:text-slate-300">{p.dte != null ? p.dte : "—"}</td>
      <td className="pr-3 text-right tabular-nums dark:text-slate-300">{num(p.position, 0)}</td>
      <td className="pr-3 text-right tabular-nums dark:text-slate-300">{num(p.mark)}</td>
      <td className="pr-3 text-right tabular-nums dark:text-slate-300">{num(p.underlying_price)}</td>
      <td className="pr-3 text-right tabular-nums dark:text-slate-300">{num(myAvg)}</td>
      <td className="pr-3 text-right tabular-nums dark:text-slate-300">{money(intrinsicMoney)}</td>
      <td className="pr-3 text-right tabular-nums dark:text-slate-300">{money(extrinsicMoney)}</td>
      <td className="pr-3 text-right tabular-nums dark:text-slate-300">{percent(p.cushion_pct)}</td>
      <td className="pr-3 text-right tabular-nums dark:text-slate-300">{percent(p.premium_captured_pct)}</td>
      <td
        className={`pr-3 text-right tabular-nums ${
          (p.unrealized_pnl ?? 0) >= 0 ? "text-emerald-600 dark:text-emerald-400" : "text-red-600 dark:text-red-400"
        }`}
      >
        {money(p.unrealized_pnl)}
      </td>
      <td className="pr-3 text-right tabular-nums dark:text-slate-300">{num(p.delta)}</td>
      <td className="text-right tabular-nums dark:text-slate-300">{num(p.theta)}</td>
    </tr>
  );
}
