import { useQuery } from "@tanstack/react-query";
import { getJSON } from "../api/client";
import type { Position } from "../api/types";

const num = (v: number | null, d = 2) => (v == null ? "—" : v.toFixed(d));
const money = (v: number | null) =>
  v == null ? "—" : v.toLocaleString(undefined, { maximumFractionDigits: 0 });

export function PositionsPanel() {
  const { data } = useQuery({
    queryKey: ["positions"],
    queryFn: () => getJSON<Position[]>("/api/positions"),
  });
  const rows = data ?? [];

  return (
    <section className="overflow-x-auto rounded-xl border border-slate-200 bg-white p-5 shadow-sm">
      <h2 className="mb-3 text-base font-semibold text-slate-800">
        Open positions{" "}
        <span className="text-sm font-normal text-slate-400">({rows.length})</span>
      </h2>
      {rows.length === 0 ? (
        <p className="text-sm text-slate-500">
          No positions yet — or the first snapshot is still being polled.
        </p>
      ) : (
        <table className="w-full text-sm">
          <thead>
            <tr className="text-left text-xs uppercase tracking-wide text-slate-400">
              <th className="py-2 pr-3">Symbol</th>
              <th className="pr-3">Type</th>
              <th className="pr-3">Strike</th>
              <th className="pr-3">Expiry</th>
              <th className="pr-3 text-right">Qty</th>
              <th className="pr-3 text-right">Mark</th>
              <th className="pr-3 text-right">Mkt val</th>
              <th className="pr-3 text-right">Unreal P&amp;L</th>
              <th className="pr-3 text-right">Δ</th>
              <th className="pr-3 text-right">Θ</th>
              <th className="text-right">IV</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((p) => (
              <tr key={p.conid} className="border-t border-slate-100">
                <td className="py-2 pr-3 font-medium text-slate-800">{p.symbol ?? "—"}</td>
                <td className="pr-3">
                  {p.sec_type}
                  {p.right ? ` ${p.right}` : ""}
                </td>
                <td className="pr-3">{p.strike ?? "—"}</td>
                <td className="pr-3">{p.expiry ?? "—"}</td>
                <td className="pr-3 text-right tabular-nums">{num(p.position, 0)}</td>
                <td className="pr-3 text-right tabular-nums">{num(p.mark)}</td>
                <td className="pr-3 text-right tabular-nums">{money(p.market_value)}</td>
                <td
                  className={`pr-3 text-right tabular-nums ${
                    (p.unrealized_pnl ?? 0) >= 0 ? "text-emerald-600" : "text-red-600"
                  }`}
                >
                  {money(p.unrealized_pnl)}
                </td>
                <td className="pr-3 text-right tabular-nums">{num(p.delta)}</td>
                <td className="pr-3 text-right tabular-nums">{num(p.theta)}</td>
                <td className="text-right tabular-nums">{p.iv == null ? "—" : num(p.iv, 1)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </section>
  );
}
