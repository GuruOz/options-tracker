import { useMemo, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { getJSON, withAccount } from "../api/client";
import type { Position } from "../api/types";
import { useAccount } from "../hooks/useAccount";

const MS_DAY = 86_400_000;

const fmtDate = (d: Date) => d.toLocaleDateString(undefined, { month: "short", day: "numeric" });
const fmtMoney = (v: number) => "$" + v.toLocaleString(undefined, { maximumFractionDigits: 0 });

// A short, human label for a position chip: "QQQ 450P".
const posLabel = (p: Position) =>
  `${p.symbol ?? "—"}${p.strike != null ? ` ${p.strike}` : ""}${p.right ?? ""}`;

const isChartable = (p: Position) => (p.decay_curve?.length ?? 0) > 1;

// Why a position can't be charted — surfaced on a muted chip / empty state instead
// of silently dropping it, so every open option stays visible with an explanation.
function decayReason(p: Position): string {
  if (p.right == null || p.strike == null) return "not an option leg";
  if (p.underlying_price == null) return `waiting for ${p.symbol ?? "the underlying"}'s spot price`;
  if (p.iv == null) return "no implied vol from the feed yet";
  if (p.dte == null || p.dte <= 0) return "expires today — no time value left to model";
  return "not modelable right now";
}

/**
 * Dedicated time-value decay panel. Reads the shared ["positions"] query (so it
 * costs no extra fetch) and charts the decay curve of whichever position is
 * selected in the table above. Framed as "time value remaining ($) over time"
 * with a hover readout; the Black–Scholes model runs under the hood.
 */
export function DecayPanel({
  selectedConid,
  onSelect,
}: {
  selectedConid: number | null;
  onSelect: (conid: number) => void;
}) {
  const { selected } = useAccount();
  const { data: positions } = useQuery({
    queryKey: ["positions", selected],
    queryFn: () => getJSON<Position[]>(withAccount("/api/positions", selected)),
  });

  const all = positions ?? [];
  const chartable = all.filter(isChartable);
  // Prefer the user's selection; otherwise default to a chartable position so the
  // panel opens on a real curve, but never hide the non-chartable ones.
  const active = all.find((p) => p.conid === selectedConid) ?? chartable[0] ?? all[0] ?? null;

  return (
    <section className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm dark:border-slate-700 dark:bg-slate-900">
      <h2 className="mb-1 text-base font-semibold text-slate-800 dark:text-slate-100">Time-value decay</h2>
      <p className="mb-3 text-xs text-slate-400 dark:text-slate-500">
        Premium time value (extrinsic) still on the contract, projected to expiry if spot and IV just sit here. Pick a
        position above — or below — to chart it.
      </p>

      {all.length === 0 ? (
        <p className="text-sm text-slate-500 dark:text-slate-400">No open option positions.</p>
      ) : (
        <>
          <div className="mb-4 flex flex-wrap gap-1.5">
            {all.map((p) => {
              const on = active?.conid === p.conid;
              const ok = isChartable(p);
              return (
                <button
                  key={p.conid}
                  onClick={() => onSelect(p.conid)}
                  title={ok ? undefined : `Can’t chart — ${decayReason(p)}`}
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
          {active && isChartable(active) ? (
            <DecayChart key={active.conid} p={active} />
          ) : active ? (
            <div className="rounded-lg border border-slate-200 bg-slate-50 px-4 py-8 text-center text-sm text-slate-500 dark:border-slate-700 dark:bg-slate-800/30 dark:text-slate-400">
              <span className="font-medium text-slate-600 dark:text-slate-300">{posLabel(active)}</span> can’t be
              charted — {decayReason(active)}.
            </div>
          ) : null}
        </>
      )}
    </section>
  );
}

function DecayChart({ p }: { p: Position }) {
  const curve = p.decay_curve!;
  const contracts = p.position != null ? Math.abs(p.position) : 1;
  const W = 760,
    H = 300,
    padL = 64,
    padR = 24,
    padT = 20,
    padB = 48;

  // Per-share extrinsic -> total dollars across all contracts, so the left-most
  // point equals the table's "Extrinsic ($)" column the desk already reads.
  const data = useMemo(
    () => curve.map((pt) => ({ dte: pt.dte, value: pt.extrinsic * 100 * contracts })),
    [curve, contracts],
  );
  const maxDte = curve[0].dte || 1;
  const maxVal = Math.max(...data.map((d) => d.value), 1e-6);
  const todayVal = data[0].value;

  // The curve is anchored to the live extrinsic only when that is positive. When the
  // mark sits at/below intrinsic (stale ITM quote) the table clamps extrinsic to $0,
  // so the backend hands back the unscaled Black-Scholes estimate instead — flag it.
  const anchored = (p.extrinsic_value ?? 0) > 0;
  const negligible = todayVal < 0.5;
  const intrinsicSh = p.intrinsic_value;

  // Time flows left (today, most DTE) -> right (expiry, 0 DTE).
  const toX = (d: number) => padL + (W - padL - padR) * (1 - d / maxDte);
  const toY = (v: number) => H - padB - (H - padT - padB) * (v / maxVal);

  // Map a remaining-DTE back to a calendar date: expiry == today + maxDte days.
  const now = Date.now();
  const dateForDte = (d: number) => new Date(now + (maxDte - d) * MS_DAY);
  const expiryDate = dateForDte(0);

  const linePts = data.map((d) => `${toX(d.dte).toFixed(1)},${toY(d.value).toFixed(1)}`);
  const line = `M ${linePts.join(" L ")}`;
  const area = `M ${toX(maxDte).toFixed(1)},${toY(0).toFixed(1)} L ${linePts.join(" L ")} L ${toX(0).toFixed(1)},${toY(0).toFixed(1)} Z`;
  const yTicks = [0, 0.25, 0.5, 0.75, 1].map((f) => f * maxVal);

  const svgRef = useRef<SVGSVGElement>(null);
  const [hoverIdx, setHoverIdx] = useState<number | null>(null);

  const onMove = (e: React.MouseEvent) => {
    const svg = svgRef.current;
    if (!svg) return;
    const rect = svg.getBoundingClientRect();
    const vbX = ((e.clientX - rect.left) / rect.width) * W; // viewBox x under cursor
    let best = 0;
    let bestD = Infinity;
    for (let i = 0; i < data.length; i++) {
      const dx = Math.abs(toX(data[i].dte) - vbX);
      if (dx < bestD) {
        bestD = dx;
        best = i;
      }
    }
    setHoverIdx(best);
  };

  const hover = hoverIdx != null ? data[hoverIdx] : null;
  const tipLeftPct = hover ? Math.min(88, Math.max(12, (toX(hover.dte) / W) * 100)) : 0;

  if (negligible) {
    return (
      <div className="rounded-lg border border-slate-200 bg-slate-50 px-4 py-8 text-center text-sm text-slate-500 dark:border-slate-700 dark:bg-slate-800/30 dark:text-slate-400">
        {p.symbol} {p.right} {p.strike} has no measurable time value left to chart
        {intrinsicSh != null && p.mark != null ? ` — mark $${p.mark.toFixed(2)} is at/below intrinsic $${intrinsicSh.toFixed(2)}` : ""}.
      </div>
    );
  }

  return (
    <div>
      <div className="mb-3 flex flex-wrap items-baseline gap-x-6 gap-y-1 text-xs">
        <span className="text-sm font-semibold text-slate-700 dark:text-slate-200">
          {p.symbol} {p.right} {p.strike}
        </span>
        <span className="text-slate-500 dark:text-slate-400">
          {anchored ? "Now: " : "Now (modeled): ≈"}
          <span className="font-semibold tabular-nums text-emerald-600 dark:text-emerald-400">{fmtMoney(todayVal)}</span>{" "}
          time value
          <span className="text-slate-400">
            {" "}
            · {contracts} contract{contracts !== 1 ? "s" : ""}
          </span>
        </span>
        <span className="text-slate-500 dark:text-slate-400">
          {p.dte}d to expiry ({fmtDate(expiryDate)})
        </span>
        {p.theta != null && (
          <span className="text-slate-500 dark:text-slate-400">
            Θ <span className="tabular-nums">{p.theta.toFixed(3)}</span>/sh/day
          </span>
        )}
      </div>

      {!anchored && (
        <div className="mb-3 rounded-md border border-amber-200 bg-amber-50 px-3 py-2 text-[11px] leading-relaxed text-amber-800 dark:border-amber-900/40 dark:bg-amber-900/15 dark:text-amber-300">
          Modeled estimate — the live mark{p.mark != null ? ` ($${p.mark.toFixed(2)})` : ""} is below intrinsic
          {intrinsicSh != null ? ` ($${intrinsicSh.toFixed(2)})` : ""}, so measured time value reads $0. This curve is the
          Black–Scholes model’s estimate of the time value remaining, not anchored to the live quote.
        </div>
      )}

      <div className="relative">
        <svg
          ref={svgRef}
          viewBox={`0 0 ${W} ${H}`}
          className="w-full"
          preserveAspectRatio="xMidYMid meet"
          onMouseMove={onMove}
          onMouseLeave={() => setHoverIdx(null)}
        >
          {yTicks.map((v, i) => (
            <g key={i}>
              <line
                x1={padL}
                y1={toY(v)}
                x2={W - padR}
                y2={toY(v)}
                className={i === 0 ? "stroke-slate-300 dark:stroke-slate-600" : "stroke-slate-100 dark:stroke-slate-800"}
                strokeWidth={1}
              />
              <text x={padL - 8} y={toY(v) + 3} textAnchor="end" className="fill-slate-400 text-[10px]">
                {fmtMoney(v)}
              </text>
            </g>
          ))}

          <path d={area} className="fill-emerald-500/10" />
          <path d={line} className="stroke-emerald-500 dark:stroke-emerald-400" strokeWidth={2} fill="none" />

          {/* today sits at the left edge (most days left) */}
          <circle cx={toX(maxDte)} cy={toY(todayVal)} r={4} className="fill-emerald-600 dark:fill-emerald-400" />

          {hover && (
            <g>
              <line
                x1={toX(hover.dte)}
                y1={padT}
                x2={toX(hover.dte)}
                y2={H - padB}
                className="stroke-slate-300 dark:stroke-slate-600"
                strokeWidth={1}
                strokeDasharray="3 3"
              />
              <circle
                cx={toX(hover.dte)}
                cy={toY(hover.value)}
                r={4}
                className="fill-white stroke-emerald-500 dark:fill-slate-900 dark:stroke-emerald-400"
                strokeWidth={2}
              />
            </g>
          )}

          {/* x axis */}
          <text x={toX(maxDte)} y={H - padB + 16} textAnchor="start" className="fill-slate-500 text-[10px]">
            Today · {fmtDate(dateForDte(maxDte))}
          </text>
          <text
            x={(toX(maxDte) + toX(0)) / 2}
            y={H - padB + 16}
            textAnchor="middle"
            className="fill-slate-400 text-[10px]"
          >
            days to expiry →
          </text>
          <text x={toX(0)} y={H - padB + 16} textAnchor="end" className="fill-slate-500 text-[10px]">
            Expiry · {fmtDate(expiryDate)}
          </text>
          <text x={toX(maxDte)} y={H - padB + 30} textAnchor="start" className="fill-slate-400 text-[9px]">
            {maxDte}d left
          </text>
          <text x={toX(0)} y={H - padB + 30} textAnchor="end" className="fill-slate-400 text-[9px]">
            0d
          </text>
        </svg>

        {hover && (
          <div
            className="pointer-events-none absolute top-0 -translate-x-1/2 rounded-md border border-slate-200 bg-white px-2.5 py-1.5 text-[11px] shadow-lg dark:border-slate-700 dark:bg-slate-800"
            style={{ left: `${tipLeftPct}%` }}
          >
            <div className="font-semibold text-slate-700 dark:text-slate-200">
              {fmtMoney(hover.value)} <span className="font-normal text-slate-400">time value</span>
            </div>
            <div className="text-slate-500 dark:text-slate-400">
              {fmtDate(dateForDte(hover.dte))} · {hover.dte}d left
            </div>
            <div className="text-slate-400">
              {todayVal > 0 ? Math.round((hover.value / todayVal) * 100) : 0}% of today’s · {fmtMoney(todayVal - hover.value)}{" "}
              decayed
            </div>
          </div>
        )}
      </div>

      <p className="mt-2 text-[10px] text-slate-400 dark:text-slate-500">
        Black–Scholes extrinsic value with spot &amp; IV held flat — isolates time decay (theta)
        {anchored ? ", anchored to the position’s current time value" : ""}. Real decay shifts with the underlying and
        vol.
      </p>
    </div>
  );
}
