import { useQuery } from "@tanstack/react-query";
import { getJSON } from "../api/client";
import type { FxResponse } from "../api/types";

/** Live FX rates into `target`, fetched only for the combined view — the
 * header converts each account's base-currency figures before summing. */
export function useFxRates(target: string, enabled: boolean) {
  const { data } = useQuery({
    queryKey: ["fx", target],
    queryFn: () => getJSON<FxResponse>(`/api/fx?target=${encodeURIComponent(target)}`),
    enabled,
    staleTime: 5 * 60_000,
  });
  return data;
}

/** The rate converting `currency` into the response's target, if resolved. */
export function rateFor(fx: FxResponse | undefined, currency: string | null): number | undefined {
  if (!fx || !currency) return undefined;
  return fx.rates.find((r) => r.currency === currency)?.rate;
}
