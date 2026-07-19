import { createContext, useCallback, useContext, useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { getJSON } from "../api/client";
import type { OwnerInfo, OwnersResponse } from "../api/types";

/** "all" for the combined household view, otherwise an owner slug. */
export type ScopeSelection = string;

export const ALL_OWNERS = "all";

const STORAGE_KEY = "selectedOwner";

interface ScopeContextValue {
  /** The owner the home/net-worth views scope to right now. */
  selected: ScopeSelection;
  setSelected: (o: ScopeSelection) => void;
  owners: OwnerInfo[];
  isAll: boolean;
}

const ScopeContext = createContext<ScopeContextValue>({
  selected: ALL_OWNERS,
  setSelected: () => {},
  owners: [],
  isAll: true,
});

function readPreference(): ScopeSelection {
  try {
    return window.localStorage.getItem(STORAGE_KEY) || ALL_OWNERS;
  } catch {
    return ALL_OWNERS;
  }
}

export function ScopeProvider({ children }: { children: React.ReactNode }) {
  const [preference, setPreference] = useState<ScopeSelection>(readPreference);

  const { data } = useQuery({
    queryKey: ["owners"],
    queryFn: () => getJSON<OwnersResponse>("/api/owners"),
  });
  const owners = useMemo(() => data?.owners ?? [], [data]);

  const setSelected = useCallback((o: ScopeSelection) => {
    setPreference(o);
    try {
      window.localStorage.setItem(STORAGE_KEY, o);
    } catch {
      /* private mode — selection just won't persist */
    }
  }, []);

  const selected = useMemo(() => {
    // Mirror useAccount: with a single owner there's nothing to combine, resolve
    // straight to it; a remembered owner that has vanished falls back to "all".
    if (owners.length === 1) return owners[0].owner;
    if (owners.length === 0) return ALL_OWNERS;
    if (preference !== ALL_OWNERS && !owners.some((o) => o.owner === preference)) {
      return ALL_OWNERS;
    }
    return preference;
  }, [owners, preference]);

  const value = useMemo(
    () => ({ selected, setSelected, owners, isAll: selected === ALL_OWNERS }),
    [selected, setSelected, owners],
  );

  return <ScopeContext.Provider value={value}>{children}</ScopeContext.Provider>;
}

/** The owner every home/net-worth query scopes to. */
export function useScope(): ScopeContextValue {
  return useContext(ScopeContext);
}
