import { useId, useMemo, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { getJSON } from "../api/client";
import type { Position } from "../api/types";
import { bsPrice, impliedVol, intrinsic, normalizeIv } from "../lib/options";

const MS_DAY = 86_400_000;

const fmtDate = (d: Date) => d.toLocaleDateString(undefined, { month: "short", day: "numeric" });
const fmtDay = (d: Date) => d.toLocaleDateString(undefined, { month: "numeric", day: "numeric" });
const signedMoney = (v: number) => (v < 0 ? "−$" : "$") + Math.round(Math.abs(v)).toLocaleString();
const signedPct = (v: number) => (v >= 0 ? "+" : "−") + Math.abs(v).toFixed(1) + "%";

const posLabel = (p: Position) =>
  `${p.symbol ?? "—"}${p.strike != null ? ` ${p.strike}` : ""}${p.right ?? ""}`;

// A position is P&L-modelable when we have everything BS needs plus an entry basis.
const canModel = (p: Position): boolean =>
  p.right != null &&
  p.strike != null &&
  p.underlying_price != null &&
  p.iv != null &&
  p.dte != null &&
  p.dte > 0 &&
  p.mark != null &&
  p.avg_cost != null &&
  p.position != null &&
  p.position !== 0;

// Why a position can't be modeled — surfaced on a muted chip / empty state instead
// of silently dropping it, so every open option stays visible with an explanation.
function modelReason(p: Position): string {
  if (p.right == null || p.strike == null) return "not an option leg";
  if (p.underlying_price == null) return `waiting for ${p.symbol ?? "the underlying"}'s spot price`;
  if (p.iv == null) return "no implied vol from the feed yet";
  if (p.dte == null || p.dte <= 0) return "expires today — nothing left to project";
  if (p.mark == null) return "no live mark";
  if (p.avg_cost == null) return "no entry cost recorded";
  return "not modelable right now";
}

// "Nice" axis step (1/2/5 × 10ⁿ) so the price rows land on round numbers.
function niceStep(raw: number): number {
  if (raw <= 0) return 1;
  const pow = Math.pow(10, Math.floor(Math.log10(raw)));
  const n = raw / pow;
  const m = n <= 1 ? 1 : n <= 2 ? 2 : n <= 5 ? 5 : 10;
  return m * pow;
}

const IV_STEPS = [-50, -30, -20, -10, -5, 0, 5, 10, 20, 30, 50];

/**
 * Profit/loss "what-if" matrix for the selected position: P&L across underlying
 * price (rows) and date (columns), Black–Scholes with spot moving and IV held (or
 * shifted). Reuses the same selection as the decay panel. Pure client-side compute.
 */
export function ProfitPanel({
  selectedConid,
  onSelect,
}: {
  selectedConid: number | null;
  onSelect: (conid: number) => void;
}) {
  const { data: positions } = useQuery({
    queryKey: ["positions"],
    queryFn: () => getJSON<Position[]>("/api/positions"),
  });

  const all = positions ?? [];
  const modelable = all.filter(canModel);
  // Prefer the user's selection; otherwise default to a modelable position so the
  // panel opens on a real grid, but never hide the non-modelable ones.
  const active = all.find((p) => p.conid === selectedConid) ?? modelable[0] ?? all[0] ?? null;

  return (
    <section className="overflow-x-auto rounded-xl border border-slate-200 bg-white p-5 shadow-sm dark:border-slate-700 dark:bg-slate-900">
      <h2 className="mb-1 text-base font-semibold text-slate-800 dark:text-slate-100">Profit / loss projection</h2>
      <p className="mb-3 text-xs text-slate-400 dark:text-slate-500">
        What the position is worth at each underlying price (rows) and date (columns) — green profit, red loss. Black–
        Scholes with spot moving and IV held flat. Pick a position above to model it.
      </p>

      {all.length === 0 ? (
        <p className="text-sm text-slate-500 dark:text-slate-400">No open option positions.</p>
      ) : (
        <>
          <div className="mb-4 flex flex-wrap gap-1.5">
            {all.map((p) => {
              const on = active?.conid === p.conid;
              const ok = canModel(p);
              return (
                <button
                  key={p.conid}
                  onClick={() => onSelect(p.conid)}
                  title={ok ? undefined : `Can’t model — ${modelReason(p)}`}
                  className={`rounded-full px-2.5 py-1 text-[11px] font-medium tabular-nums transition-colors ${
                    on
                      ? "bg-emerald-600 text-white dark:bg-emerald-500"
                      : ok
                        ? "bg-slate-100 text-slate-600 hover:bg-slate-200 dark:bg-slate-800 dark:text-slate-300 dark:hover:bg-slate-700"
                        : "border border-dashed border-slate-300 bg-transparent text-slate-400 hover:bg-slate-100 dark:border-slate-600 dark:text-slate-500 dark:hover:bg-slate-800"
                  }`}
                >
                  {posLabel(p)}
                  {!ok && <span className="ml-1 opacity-70">⚠</span>}
                </button>
              );
            })}
          </div>
          {active && canModel(active) ? (
            <ProfitChart key={active.conid} p={active} />
          ) : active ? (
            <div className="rounded-lg border border-slate-200 bg-slate-50 px-4 py-8 text-center text-sm text-slate-500 dark:border-slate-700 dark:bg-slate-800/30 dark:text-slate-400">
              <span className="font-medium text-slate-600 dark:text-slate-300">{posLabel(active)}</span> can’t be
              modeled — {modelReason(active)}.
            </div>
          ) : null}
        </>
      )}
    </section>
  );
}

type ValueMode = "pnl" | "pct";

function ProfitChart({ p }: { p: Position }) {
  const spot = p.underlying_price!;
  const K = p.strike!;
  const dte = p.dte!;
  const qty = p.position!;
  const entry = p.avg_cost!; // per-contract entry cash (credit for shorts, debit for longs)
  const isCall = (p.right ?? "").toUpperCase().startsWith("C");

  // Calibrate the model to the live mark when possible so today @ spot reproduces it.
  const ivImplied = impliedVol(isCall, spot, K, dte / 365, p.mark!);
  const usingModelIv = ivImplied == null;
  const sigmaBase = ivImplied ?? normalizeIv(p.iv!);

  const [ivChange, setIvChange] = useState(0);
  const [view, setView] = useState<"grid" | "line">("grid");
  const [valueMode, setValueMode] = useState<ValueMode>("pnl");
  const [lo, setLo] = useState(() => Math.floor((Math.min(spot, K) * 0.88) / 1) * 1);
  const [hi, setHi] = useState(() => Math.ceil(Math.max(spot, K) * 1.05));
  const [cell, setCell] = useState<{ price: number; days: number } | null>(null);

  const sigma = Math.max(1e-4, sigmaBase * (1 + ivChange / 100));
  const priceMin = Math.min(lo, hi);
  const priceMax = Math.max(lo, hi);

  // P&L of the whole position at (price, days-to-expiry). qty is signed: a short
  // (qty<0) profits as the option loses value. entry is the cash basis per contract.
  const pnlAt = (price: number, days: number) => qty * (bsPrice(isCall, price, K, days / 365, sigma) * 100 - entry);

  // Date columns: today (most DTE) on the left → expiry (0) on the right.
  const colDays = useMemo(() => {
    const step = Math.max(1, Math.ceil(dte / 11));
    const days: number[] = [];
    for (let d = dte; d > 0; d -= step) days.push(d);
    days.push(0);
    return days;
  }, [dte]);

  const now = Date.now();
  const dateFor = (days: number) => new Date(now + (dte - days) * MS_DAY);

  // Price rows: high at the top, stepped on round numbers.
  const prices = useMemo(() => {
    const step = niceStep((priceMax - priceMin) / 26);
    const top = Math.floor(priceMax / step) * step;
    const out: number[] = [];
    for (let pr = top; pr >= priceMin - 1e-9 && out.length < 60; pr -= step) out.push(Math.round(pr * 100) / 100);
    return out;
  }, [priceMin, priceMax]);

  const maxAbsPnl = useMemo(() => {
    let m = 1;
    for (const pr of prices) for (const d of colDays) m = Math.max(m, Math.abs(pnlAt(pr, d)));
    return m;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [prices, colDays, sigma, entry, qty]);

  const cellBg = (pnl: number) => {
    const a = 0.06 + 0.5 * Math.sqrt(Math.min(1, Math.abs(pnl) / maxAbsPnl));
    return pnl >= 0 ? `rgba(16,185,129,${a.toFixed(3)})` : `rgba(239,68,68,${a.toFixed(3)})`;
  };

  const spotRowIdx = useMemo(() => {
    let bi = 0;
    let bd = Infinity;
    prices.forEach((pr, i) => {
      const d = Math.abs(pr - spot);
      if (d < bd) {
        bd = d;
        bi = i;
      }
    });
    return bi;
  }, [prices, spot]);

  const maxProfit = pnlAt(isCall ? priceMin : priceMax, 0); // OTM-at-expiry side keeps full premium
  // Headline uses the broker's reported unrealized P&L (authoritative) rather than a
  // modeled value, which can drift from reality on stale/below-intrinsic ITM quotes.
  const nowPnl = p.unrealized_pnl ?? pnlAt(spot, dte);

  return (
    <div>
      {/* controls */}
      <div className="mb-4 flex flex-wrap items-end gap-x-5 gap-y-3 text-xs">
        <Control label="IV change">
          <select
            value={ivChange}
            onChange={(e) => setIvChange(Number(e.target.value))}
            className="rounded border border-slate-200 bg-white px-2 py-1 text-slate-700 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-200"
          >
            {IV_STEPS.map((s) => (
              <option key={s} value={s}>
                {s > 0 ? `+${s}` : s}%
              </option>
            ))}
          </select>
        </Control>

        <Control label="Chart style">
          <div className="flex overflow-hidden rounded border border-slate-200 dark:border-slate-700">
            <ToggleBtn on={view === "grid"} onClick={() => setView("grid")}>
              Grid
            </ToggleBtn>
            <ToggleBtn on={view === "line"} onClick={() => setView("line")}>
              Curve
            </ToggleBtn>
          </div>
        </Control>

        <Control label="Values">
          <select
            value={valueMode}
            onChange={(e) => setValueMode(e.target.value as ValueMode)}
            className="rounded border border-slate-200 bg-white px-2 py-1 text-slate-700 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-200"
          >
            <option value="pnl">$ Profit/loss</option>
            <option value="pct">% return (on basis)</option>
          </select>
        </Control>

        <Control label="Price range">
          <div className="flex items-center gap-1">
            <span className="text-slate-400">$</span>
            <input
              type="number"
              value={Math.round(lo)}
              onChange={(e) => setLo(Number(e.target.value))}
              className="w-20 rounded border border-slate-200 bg-white px-2 py-1 tabular-nums text-slate-700 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-200"
            />
            <span className="text-slate-400">–</span>
            <input
              type="number"
              value={Math.round(hi)}
              onChange={(e) => setHi(Number(e.target.value))}
              className="w-20 rounded border border-slate-200 bg-white px-2 py-1 tabular-nums text-slate-700 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-200"
            />
          </div>
        </Control>
      </div>

      {/* summary line */}
      <div className="mb-3 flex flex-wrap items-baseline gap-x-6 gap-y-1 text-xs">
        <span className="text-sm font-semibold text-slate-700 dark:text-slate-200">
          {p.symbol} {p.right} {p.strike}
        </span>
        <span className="text-slate-500 dark:text-slate-400">
          {qty < 0 ? "Short" : "Long"} {Math.abs(qty)} · spot{" "}
          <span className="tabular-nums text-slate-700 dark:text-slate-200">{spot.toFixed(2)}</span>
        </span>
        <span className="text-slate-500 dark:text-slate-400">
          Now P&amp;L:{" "}
          <span className={`font-semibold tabular-nums ${nowPnl >= 0 ? "text-emerald-600 dark:text-emerald-400" : "text-red-600 dark:text-red-400"}`}>
            {signedMoney(nowPnl)}
          </span>
        </span>
        <span className="text-slate-500 dark:text-slate-400">
          Max profit ≈ <span className="tabular-nums">{signedMoney(maxProfit)}</span>
        </span>
        <span className="text-slate-400 dark:text-slate-500">
          IV {(sigma * 100).toFixed(1)}%{ivChange !== 0 ? ` (${ivChange > 0 ? "+" : ""}${ivChange}%)` : usingModelIv ? " (quoted)" : " (implied)"}
        </span>
      </div>

      {usingModelIv && (
        <div className="mb-3 rounded-md border border-amber-200 bg-amber-50 px-3 py-2 text-[11px] leading-relaxed text-amber-800 dark:border-amber-900/40 dark:bg-amber-900/15 dark:text-amber-300">
          Live mark (${p.mark!.toFixed(2)}) is at/below intrinsic (${intrinsic(isCall, spot, K).toFixed(2)}), so the grid
          uses the quoted IV rather than an implied vol — today's column may not match the live unrealized P&amp;L.
        </div>
      )}

      {view === "grid" ? (
        <>
          <div className="overflow-x-auto">
            <table className="text-[11px] tabular-nums">
              <thead>
                <tr className="text-slate-400 dark:text-slate-500">
                  <th className="sticky left-0 bg-white px-2 py-1 text-left font-medium dark:bg-slate-900">Price</th>
                  {colDays.map((d) => (
                    <th key={d} className={`px-2 py-1 text-right font-medium ${d === 0 ? "bg-slate-100 text-slate-600 dark:bg-slate-700 dark:text-slate-200" : ""}`}>
                      {d === 0 ? "Exp" : fmtDay(dateFor(d))}
                    </th>
                  ))}
                  <th className="px-2 py-1 text-right font-medium">+/-%</th>
                </tr>
              </thead>
              <tbody>
                {prices.map((pr, ri) => {
                  const isSpot = ri === spotRowIdx;
                  return (
                    <tr key={pr} className={isSpot ? "outline outline-1 outline-blue-400/70" : ""}>
                      <td className={`sticky left-0 bg-white px-2 py-1 text-left font-semibold dark:bg-slate-900 ${isSpot ? "text-blue-600 dark:text-blue-400" : "text-slate-700 dark:text-slate-300"}`}>
                        {pr.toFixed(2)}
                        {isSpot && <span className="ml-1 text-[9px] font-normal text-blue-400">spot</span>}
                      </td>
                      {colDays.map((d) => {
                        const pnl = pnlAt(pr, d);
                        const shown = valueMode === "pnl" ? Math.round(pnl).toLocaleString() : `${(pnl / Math.abs(entry) * 100).toFixed(0)}%`;
                        const sel = cell?.price === pr && cell?.days === d;
                        return (
                          <td
                            key={d}
                            onClick={() => setCell({ price: pr, days: d })}
                            style={{ backgroundColor: cellBg(pnl) }}
                            className={`cursor-pointer px-2 py-1 text-right text-slate-800 dark:text-slate-100 ${sel ? "outline outline-2 outline-blue-500" : ""}`}
                          >
                            {shown}
                          </td>
                        );
                      })}
                      <td className={`px-2 py-1 text-right ${pr >= spot ? "text-slate-500" : "text-slate-500"} dark:text-slate-400`}>
                        {signedPct(((pr - spot) / spot) * 100)}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
          <div className="mt-2 text-[11px] text-slate-500 dark:text-slate-400">
            {cell ? (
              <CellDetail cell={cell} pnlAt={pnlAt} entry={entry} dateFor={dateFor} />
            ) : (
              <span className="text-slate-400">Click a cell to see that exit in detail.</span>
            )}
          </div>
        </>
      ) : (
        <PayoffCurve
          priceMin={priceMin}
          priceMax={priceMax}
          spot={spot}
          dte={dte}
          pnlAt={pnlAt}
          dateFor={dateFor}
        />
      )}

      <p className="mt-2 text-[10px] text-slate-400 dark:text-slate-500">
        Model assumes IV holds at {(sigma * 100).toFixed(1)}% and ignores dividends; real P&amp;L also moves with vol and
        rate changes. {qty < 0 ? "Short" : "Long"} basis is this position's avg cost — rolled chains aren't combined here.
      </p>
    </div>
  );
}

function Control({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label className="flex flex-col gap-1">
      <span className="text-[10px] font-medium uppercase tracking-wider text-slate-400 dark:text-slate-500">{label}</span>
      {children}
    </label>
  );
}

function ToggleBtn({ on, onClick, children }: { on: boolean; onClick: () => void; children: React.ReactNode }) {
  return (
    <button
      onClick={onClick}
      className={`px-3 py-1 font-medium transition-colors ${
        on ? "bg-emerald-600 text-white dark:bg-emerald-500" : "bg-white text-slate-500 hover:bg-slate-50 dark:bg-slate-900 dark:text-slate-400 dark:hover:bg-slate-800"
      }`}
    >
      {children}
    </button>
  );
}

function CellDetail({
  cell,
  pnlAt,
  entry,
  dateFor,
}: {
  cell: { price: number; days: number };
  pnlAt: (price: number, days: number) => number;
  entry: number;
  dateFor: (days: number) => Date;
}) {
  const pnl = pnlAt(cell.price, cell.days);
  const pct = (pnl / Math.abs(entry)) * 100;
  const when = cell.days === 0 ? "expiry" : fmtDate(dateFor(cell.days));
  return (
    <span>
      At <span className="font-semibold text-slate-700 dark:text-slate-200">${cell.price.toFixed(2)}</span> on{" "}
      <span className="font-semibold text-slate-700 dark:text-slate-200">{when}</span>
      {cell.days > 0 ? ` (${cell.days}d left)` : ""}:{" "}
      <span className={`font-semibold ${pnl >= 0 ? "text-emerald-600 dark:text-emerald-400" : "text-red-600 dark:text-red-400"}`}>
        {signedMoney(pnl)}
      </span>{" "}
      <span className="text-slate-400">({signedPct(pct)} on basis)</span>
    </span>
  );
}

function PayoffCurve({
  priceMin,
  priceMax,
  spot,
  dte,
  pnlAt,
  dateFor,
}: {
  priceMin: number;
  priceMax: number;
  spot: number;
  dte: number;
  pnlAt: (price: number, days: number) => number;
  dateFor: (days: number) => Date;
}) {
  const uid = useId().replace(/:/g, "");
  const W = 760,
    H = 320,
    padL = 64,
    padR = 20,
    padT = 16,
    padB = 40;
  const N = 96;

  const xs = useMemo(() => Array.from({ length: N + 1 }, (_, i) => priceMin + ((priceMax - priceMin) * i) / N), [priceMin, priceMax]);
  // Solid = today (T+0), dashed = expiry.
  const today = xs.map((x) => ({ x, y: pnlAt(x, dte) }));
  const expiry = xs.map((x) => ({ x, y: pnlAt(x, 0) }));

  const ys = [...today.map((d) => d.y), ...expiry.map((d) => d.y), 0];
  const minY = Math.min(...ys);
  const maxY = Math.max(...ys);
  const padY = (maxY - minY) * 0.08 || 1;

  const toX = (price: number) => padL + ((W - padL - padR) * (price - priceMin)) / (priceMax - priceMin || 1);
  const toY = (pnl: number) => padT + (H - padT - padB) * (1 - (pnl - (minY - padY)) / (maxY + padY - (minY - padY)));

  const path = (pts: { x: number; y: number }[]) => "M " + pts.map((d) => `${toX(d.x).toFixed(1)},${toY(d.y).toFixed(1)}`).join(" L ");
  const expiryArea =
    `M ${toX(priceMin).toFixed(1)},${toY(0).toFixed(1)} ` +
    expiry.map((d) => `L ${toX(d.x).toFixed(1)},${toY(d.y).toFixed(1)}`).join(" ") +
    ` L ${toX(priceMax).toFixed(1)},${toY(0).toFixed(1)} Z`;

  // Expiry breakevens: zero-crossings of the expiry payoff.
  const breakevens: number[] = [];
  for (let i = 1; i < expiry.length; i++) {
    const a = expiry[i - 1];
    const b = expiry[i];
    if ((a.y <= 0 && b.y >= 0) || (a.y >= 0 && b.y <= 0)) {
      const t = a.y === b.y ? 0 : -a.y / (b.y - a.y);
      breakevens.push(a.x + t * (b.x - a.x));
    }
  }

  const svgRef = useRef<SVGSVGElement>(null);
  const [hoverX, setHoverX] = useState<number | null>(null);
  const onMove = (e: React.MouseEvent) => {
    const r = svgRef.current?.getBoundingClientRect();
    if (!r) return;
    const price = priceMin + ((e.clientX - r.left) / r.width) * (priceMax - priceMin);
    setHoverX(Math.max(priceMin, Math.min(priceMax, price)));
  };
  const hoverTodayPnl = hoverX != null ? pnlAt(hoverX, dte) : null;
  const hoverExpPnl = hoverX != null ? pnlAt(hoverX, 0) : null;
  const yTicks = [minY, (minY + maxY) / 2, 0, maxY].filter((v, i, arr) => arr.indexOf(v) === i);

  return (
    <div className="relative">
      <svg
        ref={svgRef}
        viewBox={`0 0 ${W} ${H}`}
        className="w-full"
        preserveAspectRatio="xMidYMid meet"
        onMouseMove={onMove}
        onMouseLeave={() => setHoverX(null)}
      >
        <defs>
          <clipPath id={`above-${uid}`}>
            <rect x={padL} y={padT} width={W - padL - padR} height={Math.max(0, toY(0) - padT)} />
          </clipPath>
          <clipPath id={`below-${uid}`}>
            <rect x={padL} y={toY(0)} width={W - padL - padR} height={Math.max(0, H - padB - toY(0))} />
          </clipPath>
        </defs>

        {/* profit/loss shading from the expiry payoff */}
        <path d={expiryArea} fill="rgba(16,185,129,0.12)" clipPath={`url(#above-${uid})`} />
        <path d={expiryArea} fill="rgba(239,68,68,0.12)" clipPath={`url(#below-${uid})`} />

        {/* zero line + y labels */}
        {yTicks.map((v) => (
          <g key={v}>
            <line x1={padL} y1={toY(v)} x2={W - padR} y2={toY(v)} className={v === 0 ? "stroke-slate-400 dark:stroke-slate-500" : "stroke-slate-100 dark:stroke-slate-800"} strokeWidth={1} />
            <text x={padL - 6} y={toY(v) + 3} textAnchor="end" className="fill-slate-400 text-[9px]">
              {signedMoney(v)}
            </text>
          </g>
        ))}

        {/* current spot marker */}
        <line x1={toX(spot)} y1={padT} x2={toX(spot)} y2={H - padB} className="stroke-blue-400/70" strokeWidth={1} strokeDasharray="4 3" />
        <text x={toX(spot)} y={padT + 9} textAnchor="middle" className="fill-blue-400 text-[9px]">
          spot {spot.toFixed(0)}
        </text>

        {/* breakevens */}
        {breakevens.map((be, i) => (
          <g key={i}>
            <circle cx={toX(be)} cy={toY(0)} r={3} className="fill-slate-500 dark:fill-slate-300" />
            <text x={toX(be)} y={toY(0) - 6} textAnchor="middle" className="fill-slate-500 text-[9px] dark:fill-slate-300">
              BE {be.toFixed(0)}
            </text>
          </g>
        ))}

        <path d={path(expiry)} className="stroke-slate-400 dark:stroke-slate-500" strokeWidth={1.25} strokeDasharray="4 3" fill="none" />
        <path d={path(today)} className="stroke-emerald-500 dark:stroke-emerald-400" strokeWidth={2} fill="none" />

        {/* x labels */}
        <text x={padL} y={H - 8} textAnchor="start" className="fill-slate-400 text-[9px]">
          ${priceMin.toFixed(0)}
        </text>
        <text x={(padL + W - padR) / 2} y={H - 8} textAnchor="middle" className="fill-slate-400 text-[9px]">
          underlying price →
        </text>
        <text x={W - padR} y={H - 8} textAnchor="end" className="fill-slate-400 text-[9px]">
          ${priceMax.toFixed(0)}
        </text>

        {hoverX != null && (
          <>
            <line x1={toX(hoverX)} y1={padT} x2={toX(hoverX)} y2={H - padB} className="stroke-slate-300 dark:stroke-slate-600" strokeWidth={1} />
            <circle cx={toX(hoverX)} cy={toY(hoverTodayPnl!)} r={3.5} className="fill-emerald-500 dark:fill-emerald-400" />
            <circle cx={toX(hoverX)} cy={toY(hoverExpPnl!)} r={3} className="fill-slate-400 dark:fill-slate-300" />
          </>
        )}
      </svg>

      <div className="mt-1 flex flex-wrap items-center gap-x-5 gap-y-1 text-[11px] text-slate-500 dark:text-slate-400">
        <span className="flex items-center gap-1.5">
          <span className="inline-block h-0.5 w-4 bg-emerald-500" /> Today (T+0)
        </span>
        <span className="flex items-center gap-1.5">
          <span className="inline-block h-0 w-4 border-t border-dashed border-slate-400" /> At expiry ({fmtDate(dateFor(0))})
        </span>
        {hoverX != null && (
          <span className="tabular-nums">
            @ ${hoverX.toFixed(2)}: today{" "}
            <span className={hoverTodayPnl! >= 0 ? "text-emerald-600 dark:text-emerald-400" : "text-red-600 dark:text-red-400"}>
              {signedMoney(hoverTodayPnl!)}
            </span>{" "}
            · expiry{" "}
            <span className={hoverExpPnl! >= 0 ? "text-emerald-600 dark:text-emerald-400" : "text-red-600 dark:text-red-400"}>
              {signedMoney(hoverExpPnl!)}
            </span>
          </span>
        )}
      </div>
    </div>
  );
}
