import { createContext, useCallback, useContext, useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { getJSON } from "../api/client";
import type { AccountInfo } from "../api/types";

/** "all" for the combined household view, otherwise an IBKR account id. */
export type AccountSelection = string;

export const ALL_ACCOUNTS = "all";

const STORAGE_KEY = "selectedAccount";

interface AccountContextValue {
  /** The account every panel should scope its queries to right now. */
  selected: AccountSelection;
  setSelected: (a: AccountSelection) => void;
  accounts: AccountInfo[];
  isAll: boolean;
}

const AccountContext = createContext<AccountContextValue>({
  selected: ALL_ACCOUNTS,
  setSelected: () => {},
  accounts: [],
  isAll: true,
});

function readPreference(): AccountSelection {
  try {
    return window.localStorage.getItem(STORAGE_KEY) || ALL_ACCOUNTS;
  } catch {
    return ALL_ACCOUNTS;
  }
}

export function AccountProvider({ children }: { children: React.ReactNode }) {
  // The user's *raw* preference — meaningful once there's something to choose
  // between. With 0 or 1 accounts there's nothing to combine, so it's ignored
  // below in favor of resolving straight to that one account (or "all" if none
  // exist yet). This keeps a single-user deployment fully editable without the
  // user ever having to think about a switcher they'll never see.
  const [preference, setPreference] = useState<AccountSelection>(readPreference);

  const { data: accountsData } = useQuery({
    queryKey: ["accounts"],
    queryFn: () => getJSON<AccountInfo[]>("/api/accounts"),
  });
  const accounts = accountsData ?? [];

  const setSelected = useCallback((a: AccountSelection) => {
    setPreference(a);
    try {
      window.localStorage.setItem(STORAGE_KEY, a);
    } catch {
      /* private mode — selection just won't persist */
    }
  }, []);

  const selected = useMemo(() => {
    if (accounts.length === 1) return accounts[0].account_id;
    if (accounts.length === 0) return ALL_ACCOUNTS;
    // A remembered account can vanish (renamed compose project, wiped volume);
    // fall back to the combined view rather than querying a dead id.
    if (preference !== ALL_ACCOUNTS && !accounts.some((a) => a.account_id === preference)) {
      return ALL_ACCOUNTS;
    }
    return preference;
  }, [accounts, preference]);

  const value = useMemo(
    () => ({
      selected,
      setSelected,
      accounts,
      isAll: selected === ALL_ACCOUNTS,
    }),
    [selected, setSelected, accounts],
  );

  return <AccountContext.Provider value={value}>{children}</AccountContext.Provider>;
}

/** The account every panel scopes its queries to. */
export function useAccount(): AccountContextValue {
  return useContext(AccountContext);
}
