import { useMemo, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { getJSON } from "../api/client";
import type { Market, MarketHistory, MarketHistoryPoint } from "../api/types";

const fmtAxisDate = (d: Date) =>
  d.toLocaleDateString(undefined, { month: "short", year: "2-digit" });
const fmtFullDate = (d: Date) =>
  d.toLocaleDateString(undefined, { month: "short", day: "numeric", year: "numeric" });
const fmtPrice = (v: number) =>
  "$" + v.toLocaleString(undefined, { maximumFractionDigits: v >= 100 ? 0 : 2 });
const fmtNum = (v: number | null, digits = 1) => (v == null ? "—" : v.toFixed(digits));

const SOURCE_LABEL: Record<string, string> = {
  ibkr: "IBKR",
  public: "Public (yfinance)",
  cache: "Cached",
};

/**
 * Spec panel 6 — Market context.
 *
 * The user types any ticker symbol to load its price chart. Data is read from
 * the daily-bar cache; if the symbol isn't cached yet, the backend fetches it
 * from yfinance on-demand (2y history). The chart shows price + 50-day SMA +
 * 200-day SMA + a VIX sub-pane. Stats (IV, RV, etc.) appear when the symbol
 * is also a tracked underlying with market-snapshot data.
 */
export function MarketContextPanel() {
  const [inputVal, setInputVal] = useState("");
  const [activeTicker, setActiveTicker] = useState<string | null>(null);
  const [recentTickers, setRecentTickers] = useState<string[]>([]);

  const handleLoad = (sym?: string) => {
    const ticker = (sym ?? inputVal).trim().toUpperCase();
    if (!ticker) return;
    setActiveTicker(ticker);
    setInputVal("");
    setRecentTickers((prev) => [ticker, ...prev.filter((t) => t !== ticker)].slice(0, 8));
  };

  return (
    <section className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm dark:border-slate-700 dark:bg-slate-900">
      <div className="mb-3 flex items-baseline justify-between">
        <h2 className="text-base font-semibold text-slate-800 dark:text-slate-100">Market context</h2>
        <span className="text-xs text-slate-400 dark:text-slate-500">price · SMA 50 · SMA 200 · VIX</span>
      </div>

      {/* Ticker search */}
      <div className="mb-3 flex gap-2">
        <input
          type="text"
          value={inputVal}
          onChange={(e) => setInputVal(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && handleLoad()}
          placeholder="Ticker symbol (e.g. AAPL, SPY, ^VIX)"
          className="flex-1 rounded-lg border border-slate-200 bg-slate-50 px-3 py-1.5 text-sm text-slate-800 placeholder-slate-400 focus:border-sky-400 focus:outline-none dark:border-slate-600 dark:bg-slate-800 dark:text-slate-100 dark:placeholder-slate-500"
        />
        <button
          onClick={() => handleLoad()}
          disabled={!inputVal.trim()}
          className="rounded-lg bg-sky-600 px-3 py-1.5 text-sm font-medium text-white transition-colors hover:bg-sky-700 disabled:opacity-40 dark:bg-sky-500 dark:hover:bg-sky-600"
        >
          Load
        </button>
      </div>

      {/* Recent ticker chips */}
      {recentTickers.length > 0 && (
        <div className="mb-4 flex flex-wrap gap-1.5">
          {recentTickers.map((sym) => (
            <button
              key={sym}
              onClick={() => handleLoad(sym)}
              className={`rounded-full px-2.5 py-1 text-[11px] font-medium transition-colors ${
                activeTicker === sym
                  ? "bg-sky-600 text-white dark:bg-sky-500"
                  : "bg-slate-100 text-slate-600 hover:bg-slate-200 dark:bg-slate-800 dark:text-slate-300 dark:hover:bg-slate-700"
              }`}
            >
              {sym}
            </button>
          ))}
        </div>
      )}

      {activeTicker ? (
        <MarketChartLoader symbol={activeTicker} />
      ) : (
        <p className="py-6 text-center text-sm text-slate-400 dark:text-slate-500">
          Enter any ticker symbol above to load its price history.
        </p>
      )}
    </section>
  );
}

function MarketChartLoader({ symbol }: { symbol: string }) {
  const { data, isLoading, isError, error } = useQuery({
    queryKey: ["market", "history", "symbol", symbol],
    queryFn: () =>
      getJSON<MarketHistory>(`/api/market/history/by-symbol?symbol=${encodeURIComponent(symbol)}&months=12`),
    staleTime: 300_000,
    retry: false,
  });

  if (isLoading) {
    return (
      <div className="py-10 text-center text-sm text-slate-400 dark:text-slate-500">
        Loading price history for {symbol}…
      </div>
    );
  }
  if (isError) {
    const msg = (error as { detail?: string })?.detail;
    return (
      <div className="rounded-lg border border-rose-200 bg-rose-50 px-4 py-6 text-center text-sm text-rose-600 dark:border-rose-800 dark:bg-rose-900/20 dark:text-rose-400">
        {msg ?? `No price data found for ${symbol}.`}
      </div>
    );
  }
  if (!data) return null;

  return (
    <>
      {data.market && <StatRow m={data.market} />}
      <MarketChart symbol={symbol} data={data} />
    </>
  );
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <div className="text-[10px] uppercase tracking-wide text-slate-400 dark:text-slate-500">{label}</div>
      <div className="text-sm font-semibold tabular-nums text-slate-700 dark:text-slate-200">{value}</div>
    </div>
  );
}

function StatRow({ m }: { m: Market }) {
  return (
    <div className="mb-4 flex flex-wrap items-end gap-x-6 gap-y-3">
      <Stat label="Spot (USD)" value={m.price != null ? fmtPrice(m.price) : "—"} />
      <Stat label="IV" value={m.iv != null ? `${fmtNum(m.iv)}%` : "—"} />
      <Stat label="RV (20d)" value={m.realized_vol != null ? `${fmtNum(m.realized_vol)}%` : "—"} />
      <Stat label="IV %ile" value={m.iv_percentile != null ? fmtNum(m.iv_percentile, 0) : "—"} />
      <Stat label="RSI (14)" value={fmtNum(m.rsi14, 0)} />
      <Stat label="SMA 50" value={m.sma50 != null ? fmtPrice(m.sma50) : "—"} />
      <Stat label="SMA 200" value={m.sma200 != null ? fmtPrice(m.sma200) : "—"} />
      {m.source && (
        <span className="ml-auto rounded-full bg-slate-100 px-2 py-0.5 text-[10px] font-medium text-slate-500 dark:bg-slate-800 dark:text-slate-400">
          {SOURCE_LABEL[m.source] ?? m.source}
        </span>
      )}
    </div>
  );
}

type Pt = {
  i: number;
  date: Date;
  close: number | null;
  sma: number | null;
  sma200: number | null;
  vix: number | null;
};

function pathOf(
  points: Pt[],
  toX: (i: number) => number,
  toY: (v: number) => number,
  pick: (p: Pt) => number | null,
): string {
  let d = "";
  let pen = false;
  for (const p of points) {
    const v = pick(p);
    if (v == null) {
      pen = false;
      continue;
    }
    d += `${pen ? "L" : "M"} ${toX(p.i).toFixed(1)},${toY(v).toFixed(1)} `;
    pen = true;
  }
  return d.trim();
}

function MarketChart({ symbol, data }: { symbol: string; data: MarketHistory }) {
  const [months, setMonths] = useState<6 | 12>(6);
  const [showVix, setShowVix] = useState(true);

  const all: MarketHistoryPoint[] = data.points;

  const cutoff = useMemo(() => {
    const c = new Date();
    c.setMonth(c.getMonth() - months);
    return c;
  }, [months]);

  const points: Pt[] = useMemo(
    () =>
      all
        .map((p) => ({ ...p, date: new Date(p.date + "T00:00:00") }))
        .filter((p) => p.date >= cutoff)
        .map((p, i) => ({
          i,
          date: p.date,
          close: p.close,
          sma: p.sma,
          sma200: p.sma200,
          vix: p.vix,
        })),
    [all, cutoff],
  );

  const svgRef = useRef<SVGSVGElement>(null);
  const [hoverIdx, setHoverIdx] = useState<number | null>(null);

  if (points.length < 2) {
    return (
      <div className="rounded-lg border border-slate-200 bg-slate-50 px-4 py-8 text-center text-sm text-slate-500 dark:border-slate-700 dark:bg-slate-800/30 dark:text-slate-400">
        Building daily price history for {symbol} — check back shortly.
      </div>
    );
  }

  const W = 800,
    H = 400,
    padL = 56,
    padR = 48,
    padT = 14,
    padB = 46;
  const priceTop = padT;
  const priceH = 230;
  const priceBottom = priceTop + priceH;
  const vixActive = showVix && points.some((p) => p.vix != null);
  const vixTop = priceBottom + 30;
  const vixH = vixActive ? 64 : 0;
  const vixBottom = vixTop + vixH;

  const n = points.length;
  const toX = (i: number) => padL + ((W - padL - padR) * i) / (n - 1);

  const priceVals = points.flatMap((p) =>
    [p.close, p.sma, p.sma200].filter((v): v is number => v != null),
  );
  let pMin = Math.min(...priceVals);
  let pMax = Math.max(...priceVals);
  const pPad = (pMax - pMin || pMax || 1) * 0.06;
  pMin -= pPad;
  pMax += pPad;
  const toYp = (v: number) => priceBottom - ((v - pMin) / (pMax - pMin || 1)) * priceH;

  const vixVals = points.map((p) => p.vix).filter((v): v is number => v != null);
  const vMin = vixVals.length ? Math.min(...vixVals) : 0;
  const vMax = vixVals.length ? Math.max(...vixVals) : 1;
  const toYv = (v: number) => vixBottom - ((v - vMin) / (vMax - vMin || 1)) * vixH;

  const priceLine = pathOf(points, toX, toYp, (p) => p.close);
  const smaLine = pathOf(points, toX, toYp, (p) => p.sma);
  const sma200Line = pathOf(points, toX, toYp, (p) => p.sma200);
  const priceArea = priceLine
    ? `${priceLine} L ${toX(n - 1).toFixed(1)},${toYp(pMin).toFixed(1)} L ${toX(0).toFixed(1)},${toYp(pMin).toFixed(1)} Z`
    : "";
  const vixLine = vixActive ? pathOf(points, toX, toYv, (p) => p.vix) : "";

  const priceTicks = [0, 0.25, 0.5, 0.75, 1].map((f) => pMin + f * (pMax - pMin));
  const dateTickIdx = Array.from({ length: Math.min(6, n) }, (_, k) =>
    Math.round((k * (n - 1)) / (Math.min(6, n) - 1)),
  );

  const onMove = (e: React.MouseEvent) => {
    const svg = svgRef.current;
    if (!svg) return;
    const rect = svg.getBoundingClientRect();
    const vbX = ((e.clientX - rect.left) / rect.width) * W;
    let best = 0,
      bestD = Infinity;
    for (let i = 0; i < n; i++) {
      const dx = Math.abs(toX(i) - vbX);
      if (dx < bestD) {
        bestD = dx;
        best = i;
      }
    }
    setHoverIdx(best);
  };

  const hover = hoverIdx != null ? points[hoverIdx] : null;
  const tipLeftPct = hover ? Math.min(86, Math.max(14, (toX(hover.i) / W) * 100)) : 0;
  const lastClose = points[n - 1].close;
  const firstClose = points.find((p) => p.close != null)?.close ?? null;
  const pctChange =
    firstClose != null && lastClose != null && firstClose !== 0
      ? ((lastClose - firstClose) / firstClose) * 100
      : null;

  const hasSma200 = points.some((p) => p.sma200 != null);

  return (
    <div>
      <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
        <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-[11px]">
          <LegendDot stroke="stroke-sky-500 dark:stroke-sky-400" label={`${symbol} price`} />
          <LegendDot stroke="stroke-amber-500 dark:stroke-amber-400" label="SMA 50" dashed />
          {hasSma200 && (
            <LegendDot stroke="stroke-rose-500 dark:stroke-rose-400" label="SMA 200" dashed />
          )}
          {vixActive && (
            <LegendDot stroke="stroke-violet-500 dark:stroke-violet-400" label="VIX (market-wide)" />
          )}
          {pctChange != null && (
            <span
              className={`font-semibold tabular-nums ${
                pctChange >= 0 ? "text-emerald-600 dark:text-emerald-400" : "text-rose-600 dark:text-rose-400"
              }`}
            >
              {pctChange >= 0 ? "+" : ""}
              {pctChange.toFixed(1)}% / {months}mo
            </span>
          )}
        </div>
        <div className="flex items-center gap-1.5">
          <button
            onClick={() => setShowVix((v) => !v)}
            className={`rounded-md px-2 py-0.5 text-[11px] font-medium transition-colors ${
              showVix
                ? "bg-violet-100 text-violet-700 dark:bg-violet-900/40 dark:text-violet-300"
                : "bg-slate-100 text-slate-500 dark:bg-slate-800 dark:text-slate-400"
            }`}
          >
            VIX
          </button>
          {([6, 12] as const).map((m) => (
            <button
              key={m}
              onClick={() => setMonths(m)}
              className={`rounded-md px-2 py-0.5 text-[11px] font-medium transition-colors ${
                months === m
                  ? "bg-sky-600 text-white dark:bg-sky-500"
                  : "bg-slate-100 text-slate-500 hover:bg-slate-200 dark:bg-slate-800 dark:text-slate-400 dark:hover:bg-slate-700"
              }`}
            >
              {m}M
            </button>
          ))}
        </div>
      </div>

      <div className="relative">
        <svg
          ref={svgRef}
          viewBox={`0 0 ${W} ${H}`}
          className="w-full"
          preserveAspectRatio="xMidYMid meet"
          onMouseMove={onMove}
          onMouseLeave={() => setHoverIdx(null)}
        >
          {/* price gridlines + y-axis */}
          {priceTicks.map((v, i) => (
            <g key={i}>
              <line
                x1={padL}
                y1={toYp(v)}
                x2={W - padR}
                y2={toYp(v)}
                className={
                  i === 0
                    ? "stroke-slate-300 dark:stroke-slate-600"
                    : "stroke-slate-100 dark:stroke-slate-800"
                }
                strokeWidth={1}
              />
              <text x={padL - 8} y={toYp(v) + 3} textAnchor="end" className="fill-slate-400 text-[10px]">
                {fmtPrice(v)}
              </text>
            </g>
          ))}

          <path d={priceArea} className="fill-sky-500/10" />
          <path
            d={sma200Line}
            className="stroke-rose-500 dark:stroke-rose-400"
            strokeWidth={1.5}
            strokeDasharray="6 3"
            fill="none"
          />
          <path
            d={smaLine}
            className="stroke-amber-500 dark:stroke-amber-400"
            strokeWidth={1.5}
            strokeDasharray="4 3"
            fill="none"
          />
          <path d={priceLine} className="stroke-sky-500 dark:stroke-sky-400" strokeWidth={2} fill="none" />

          {/* VIX sub-pane */}
          {vixActive && (
            <>
              <text
                x={W - padR + 6}
                y={toYv(vMax) + 3}
                textAnchor="start"
                className="fill-slate-400 text-[10px]"
              >
                {vMax.toFixed(0)}
              </text>
              <text
                x={W - padR + 6}
                y={toYv(vMin) + 3}
                textAnchor="start"
                className="fill-slate-400 text-[10px]"
              >
                {vMin.toFixed(0)}
              </text>
              <text
                x={padL}
                y={vixTop - 6}
                textAnchor="start"
                className="fill-violet-500 text-[10px] font-medium dark:fill-violet-400"
              >
                VIX
              </text>
              <path
                d={vixLine}
                className="stroke-violet-500 dark:stroke-violet-400"
                strokeWidth={1.5}
                fill="none"
              />
            </>
          )}

          {/* x-axis date labels */}
          {dateTickIdx.map((idx) => (
            <text
              key={idx}
              x={toX(idx)}
              y={H - padB + 18}
              textAnchor={idx === 0 ? "start" : idx === n - 1 ? "end" : "middle"}
              className="fill-slate-400 text-[10px]"
            >
              {fmtAxisDate(points[idx].date)}
            </text>
          ))}

          {/* hover crosshair */}
          {hover && (
            <g>
              <line
                x1={toX(hover.i)}
                y1={priceTop}
                x2={toX(hover.i)}
                y2={vixActive ? vixBottom : priceBottom}
                className="stroke-slate-300 dark:stroke-slate-600"
                strokeWidth={1}
                strokeDasharray="3 3"
              />
              {hover.close != null && (
                <circle
                  cx={toX(hover.i)}
                  cy={toYp(hover.close)}
                  r={3.5}
                  className="fill-white stroke-sky-500 dark:fill-slate-900 dark:stroke-sky-400"
                  strokeWidth={2}
                />
              )}
              {vixActive && hover.vix != null && (
                <circle
                  cx={toX(hover.i)}
                  cy={toYv(hover.vix)}
                  r={3}
                  className="fill-white stroke-violet-500 dark:fill-slate-900 dark:stroke-violet-400"
                  strokeWidth={2}
                />
              )}
            </g>
          )}
        </svg>

        {hover && (
          <div
            className="pointer-events-none absolute top-0 -translate-x-1/2 rounded-md border border-slate-200 bg-white px-2.5 py-1.5 text-[11px] shadow-lg dark:border-slate-700 dark:bg-slate-800"
            style={{ left: `${tipLeftPct}%` }}
          >
            <div className="font-semibold text-slate-700 dark:text-slate-200">{fmtFullDate(hover.date)}</div>
            <div className="text-slate-500 dark:text-slate-400">
              {symbol}{" "}
              <span className="font-semibold tabular-nums text-sky-600 dark:text-sky-400">
                {hover.close != null ? fmtPrice(hover.close) : "—"}
              </span>
            </div>
            <div className="text-slate-500 dark:text-slate-400">
              SMA 50 <span className="tabular-nums">{hover.sma != null ? fmtPrice(hover.sma) : "—"}</span>
            </div>
            {hover.sma200 != null && (
              <div className="text-slate-500 dark:text-slate-400">
                SMA 200{" "}
                <span className="tabular-nums text-rose-600 dark:text-rose-400">
                  {fmtPrice(hover.sma200)}
                </span>
              </div>
            )}
            {vixActive && (
              <div className="text-slate-500 dark:text-slate-400">
                VIX{" "}
                <span className="tabular-nums text-violet-600 dark:text-violet-400">
                  {hover.vix != null ? hover.vix.toFixed(1) : "—"}
                </span>
              </div>
            )}
          </div>
        )}
      </div>

      <p className="mt-2 text-[10px] text-slate-400 dark:text-slate-500">
        Daily closes from the DB cache (yfinance, 2y). SMA 200 requires ~200 trading-day lead-in — it
        populates at the tail end of the 12M view and fully on the 6M view. VIX is market-wide.
      </p>
    </div>
  );
}

function LegendDot({ stroke, label, dashed }: { stroke: string; label: string; dashed?: boolean }) {
  return (
    <span className="flex items-center gap-1.5 text-slate-500 dark:text-slate-400">
      <svg width="16" height="6" aria-hidden>
        <line
          x1="0"
          y1="3"
          x2="16"
          y2="3"
          className={stroke}
          strokeWidth={2}
          strokeDasharray={dashed ? "4 3" : undefined}
        />
      </svg>
      {label}
    </span>
  );
}
