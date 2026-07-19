import { createContext, useCallback, useContext, useMemo, useState } from "react";
import { useAccount } from "./useAccount";

/** The currency the combined "All" view converts household totals into.
 * Single-account views ignore it — each account keeps its own base currency. */

const STORAGE_KEY = "displayCurrency";
const DEFAULT_CURRENCY = "USD";

interface DisplayCurrencyValue {
  currency: string;
  setCurrency: (c: string) => void;
  /** The currencies worth offering: the accounts' base currencies, USD first. */
  options: string[];
}

const DisplayCurrencyContext = createContext<DisplayCurrencyValue>({
  currency: DEFAULT_CURRENCY,
  setCurrency: () => {},
  options: [DEFAULT_CURRENCY],
});

function readPreference(): string {
  try {
    return window.localStorage.getItem(STORAGE_KEY) || DEFAULT_CURRENCY;
  } catch {
    return DEFAULT_CURRENCY;
  }
}

export function DisplayCurrencyProvider({ children }: { children: React.ReactNode }) {
  const { accounts } = useAccount();
  const [preference, setPreference] = useState<string>(readPreference);

  const options = useMemo(() => {
    const ccys = new Set(
      accounts.map((a) => a.base_currency).filter((c): c is string => !!c),
    );
    ccys.add(DEFAULT_CURRENCY);
    return [...ccys].sort((a, b) =>
      a === DEFAULT_CURRENCY ? -1 : b === DEFAULT_CURRENCY ? 1 : a.localeCompare(b),
    );
  }, [accounts]);

  const setCurrency = useCallback((c: string) => {
    setPreference(c);
    try {
      window.localStorage.setItem(STORAGE_KEY, c);
    } catch {
      /* private mode — preference just won't persist */
    }
  }, []);

  // A remembered currency no account uses anymore falls back to the default.
  const currency = options.includes(preference) ? preference : DEFAULT_CURRENCY;

  const value = useMemo(
    () => ({ currency, setCurrency, options }),
    [currency, setCurrency, options],
  );

  return (
    <DisplayCurrencyContext.Provider value={value}>
      {children}
    </DisplayCurrencyContext.Provider>
  );
}

/** The display currency for combined-view money figures. */
export function useDisplayCurrency(): DisplayCurrencyValue {
  return useContext(DisplayCurrencyContext);
}
