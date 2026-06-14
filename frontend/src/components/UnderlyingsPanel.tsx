import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";
import { getJSON, deleteJSON, postJSON } from "../api/client";
import type { ContractResult } from "../api/types";

interface Underlying {
  conid: number;
  symbol: string;
  description?: string;
}

interface Settings {
  underlyings: Underlying[];
}

function useDebounce(value: string, ms: number) {
  const [debounced, setDebounced] = useState(value);
  useEffect(() => {
    const t = setTimeout(() => setDebounced(value), ms);
    return () => clearTimeout(t);
  }, [value, ms]);
  return debounced;
}

export function UnderlyingsPanel() {
  const qc = useQueryClient();
  const [query, setQuery] = useState("");
  const [open, setOpen] = useState(false);
  const debouncedQ = useDebounce(query, 300);
  const inputRef = useRef<HTMLInputElement>(null);
  const dropdownRef = useRef<HTMLDivElement>(null);

  const { data: settings } = useQuery({
    queryKey: ["settings"],
    queryFn: () => getJSON<Settings>("/api/settings"),
  });

  const { data: searchResults = [], isFetching: searching } = useQuery({
    queryKey: ["contract-search", debouncedQ],
    queryFn: () =>
      debouncedQ.length >= 1
        ? getJSON<ContractResult[]>(`/api/contracts/search?q=${encodeURIComponent(debouncedQ)}`)
        : Promise.resolve([]),
    enabled: debouncedQ.length >= 1,
  });

  const tracked = settings?.underlyings ?? [];

  const addMutation = useMutation({
    mutationFn: (u: ContractResult) =>
      postJSON("/api/settings/underlyings", u),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["settings"] });
      setQuery("");
      setOpen(false);
    },
  });

  const removeMutation = useMutation({
    mutationFn: (conid: number) =>
      deleteJSON(`/api/settings/underlyings/${conid}`),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["settings"] }),
  });

  // Close dropdown when clicking outside
  useEffect(() => {
    function handle(e: MouseEvent) {
      if (
        dropdownRef.current &&
        !dropdownRef.current.contains(e.target as Node) &&
        inputRef.current &&
        !inputRef.current.contains(e.target as Node)
      ) {
        setOpen(false);
      }
    }
    document.addEventListener("mousedown", handle);
    return () => document.removeEventListener("mousedown", handle);
  }, []);

  const alreadyTracked = new Set(tracked.map((u) => u.conid));

  return (
    <section className="rounded-xl border border-slate-200 bg-white px-5 py-4 shadow-sm">
      <div className="flex flex-wrap items-center gap-x-4 gap-y-3">
        <p className="text-sm font-semibold text-slate-700 shrink-0">Tracked underlyings</p>

        {/* Current tracked list */}
        <div className="flex flex-wrap gap-2">
          {tracked.length === 0 && (
            <span className="text-xs text-slate-400 italic">None — add a ticker below</span>
          )}
          {tracked.map((u) => (
            <span
              key={u.conid}
              className="inline-flex items-center gap-1 rounded-full bg-slate-100 px-3 py-1 text-xs font-semibold text-slate-700"
            >
              {u.symbol}
              <button
                onClick={() => removeMutation.mutate(u.conid)}
                disabled={removeMutation.isPending}
                aria-label={`Remove ${u.symbol}`}
                className="ml-0.5 text-slate-400 hover:text-red-500 leading-none"
              >
                ×
              </button>
            </span>
          ))}
        </div>

        {/* Search box */}
        <div className="relative ml-auto">
          <input
            ref={inputRef}
            type="text"
            placeholder="Add ticker…"
            value={query}
            onChange={(e) => {
              setQuery(e.target.value);
              setOpen(true);
            }}
            onFocus={() => query.length >= 1 && setOpen(true)}
            className="w-36 rounded-lg border border-slate-300 bg-white px-3 py-1.5 text-sm placeholder:text-slate-400 focus:border-blue-400 focus:outline-none focus:ring-2 focus:ring-blue-100"
          />

          {open && debouncedQ.length >= 1 && (
            <div
              ref={dropdownRef}
              className="absolute right-0 top-full z-20 mt-1 w-72 rounded-xl border border-slate-200 bg-white shadow-lg"
            >
              {searching && (
                <p className="px-3 py-2 text-xs text-slate-400">Searching…</p>
              )}
              {!searching && searchResults.length === 0 && (
                <p className="px-3 py-2 text-xs text-slate-400">No results</p>
              )}
              {searchResults.map((r) => {
                const added = alreadyTracked.has(r.conid);
                return (
                  <button
                    key={r.conid}
                    disabled={added || addMutation.isPending}
                    onClick={() => addMutation.mutate(r)}
                    className={`flex w-full items-start gap-3 px-3 py-2 text-left hover:bg-slate-50 first:rounded-t-xl last:rounded-b-xl disabled:cursor-default ${
                      added ? "opacity-40" : ""
                    }`}
                  >
                    <span className="mt-0.5 min-w-[2.5rem] text-xs font-bold text-slate-800">
                      {r.symbol}
                    </span>
                    <span className="truncate text-xs text-slate-500">{r.description}</span>
                    {added && (
                      <span className="ml-auto shrink-0 text-xs text-emerald-600">✓</span>
                    )}
                  </button>
                );
              })}
            </div>
          )}
        </div>
      </div>
    </section>
  );
}
