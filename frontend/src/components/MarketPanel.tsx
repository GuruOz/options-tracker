import { useQuery } from "@tanstack/react-query";
import { getJSON } from "../api/client";
import type { Market } from "../api/types";

const num = (v: number | null, d = 2) => (v == null ? "—" : v.toFixed(d));
const round = (v: number | null) => (v == null ? "—" : Math.round(v).toString());

export function MarketPanel() {
  const { data } = useQuery({
    queryKey: ["market"],
    queryFn: () => getJSON<Market[]>("/api/market"),
  });
  const rows = data ?? [];

  return (
    <section className="overflow-x-auto rounded-xl border border-slate-200 bg-white p-5 shadow-sm">
      <h2 className="mb-3 text-base font-semibold text-slate-800">Market context</h2>
      {rows.length === 0 ? (
        <p className="text-sm text-slate-500">No market data yet.</p>
      ) : (
        <table className="w-full text-sm">
          <thead>
            <tr className="text-left text-xs uppercase tracking-wide text-slate-400">
              <th className="py-2 pr-3">Symbol</th>
              <th className="pr-3 text-right">Price</th>
              <th className="pr-3 text-right">IV %</th>
              <th className="pr-3 text-right">RV %</th>
              <th className="pr-3 text-right">IV %ile</th>
              <th className="pr-3 text-right">RSI</th>
              <th className="pr-3 text-right">SMA50</th>
              <th className="text-right">SMA200</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((m) => (
              <tr key={m.conid} className="border-t border-slate-100">
                <td className="py-2 pr-3 font-medium text-slate-800">
                  {m.symbol ?? m.conid}
                </td>
                <td className="pr-3 text-right tabular-nums">{num(m.price)}</td>
                <td className="pr-3 text-right tabular-nums">{num(m.iv, 1)}</td>
                <td className="pr-3 text-right tabular-nums">{num(m.realized_vol, 1)}</td>
                <td className="pr-3 text-right tabular-nums">{round(m.iv_percentile)}</td>
                <td className="pr-3 text-right tabular-nums">{round(m.rsi14)}</td>
                <td className="pr-3 text-right tabular-nums">{num(m.sma50)}</td>
                <td className="text-right tabular-nums">{num(m.sma200)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </section>
  );
}
