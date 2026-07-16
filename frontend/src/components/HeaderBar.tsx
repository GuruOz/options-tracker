import { useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { getJSON, postJSON, withAccount } from "../api/client";
import type { AccountInfo, AccountSummary, PullResult, SessionMap, SessionState } from "../api/types";
import { ALL_ACCOUNTS, useAccount } from "../hooks/useAccount";

// Falls back to USD when an account's base currency hasn't been reported yet
// (e.g. a brand-new account before its first summary poll) - matches the
// pre-currency-tracking behavior rather than showing something worse.
const money = (v: number | null | undefined, currency = "USD") =>
  v == null
    ? "—"
    : v.toLocaleString(undefined, {
        style: "currency",
        currency,
        maximumFractionDigits: 0,
      });

const STATUS_DOT: Record<string, string> = {
  authenticated: "bg-emerald-500",
  pulling: "bg-blue-500",
  logging_in: "bg-amber-400",
  disconnected: "bg-amber-400",
  unknown: "bg-slate-400",
};

const STATUS_TEXT: Record<string, string> = {
  authenticated: "text-emerald-700",
  pulling: "text-blue-700",
  logging_in: "text-amber-700",
  disconnected: "text-amber-700",
  unknown: "text-slate-500",
};

const SOURCE_BADGE: Record<string, string> = {
  ibkr_live: "bg-emerald-100 text-emerald-800 dark:bg-emerald-900 dark:text-emerald-200",
  public: "bg-blue-100 text-blue-800 dark:bg-blue-900 dark:text-blue-200",
  cache: "bg-slate-100 text-slate-500 dark:bg-slate-800 dark:text-slate-400",
};

const SOURCE_LABEL: Record<string, string> = {
  ibkr_live: "IBKR live",
  public: "public",
  cache: "cached",
};

const STATS: { label: string; key: keyof AccountSummary }[] = [
  { label: "Net liq.", key: "net_liquidation" },
  { label: "Available", key: "available_funds" },
  { label: "Excess liq.", key: "excess_liquidity" },
  { label: "Maint. margin", key: "maintenance_margin" },
  { label: "Cash", key: "cash" },
];

/** Sum a stat across accounts, or null when nobody has reported one yet. */
function sumStat(accounts: AccountInfo[], key: keyof AccountSummary): number | null {
  const vals = accounts
    .map((a) => a[key as keyof AccountInfo] as number | null)
    .filter((v): v is number => v != null);
  return vals.length ? vals.reduce((a, b) => a + b, 0) : null;
}

/** One user's connection dot, message, and login/logout button. */
function GatewayControls({
  session,
  compact,
}: {
  session: SessionState;
  compact: boolean;
}) {
  const [loggingIn, setLoggingIn] = useState(false);
  const [loggingOut, setLoggingOut] = useState(false);
  const queryClient = useQueryClient();

  const dotClass = STATUS_DOT[session.status] ?? STATUS_DOT.unknown;
  const textClass = STATUS_TEXT[session.status] ?? STATUS_TEXT.unknown;
  const checked = session.last_checked
    ? new Date(session.last_checked).toLocaleTimeString()
    : "—";

  const handleLogin = async () => {
    setLoggingIn(true);
    try {
      const result = await postJSON<PullResult>(
        `/api/session/${session.gateway_id}/login`,
        {},
      );
      if (result.status === "ok") {
        queryClient.invalidateQueries();
      }
    } catch {
      /* state updated via WebSocket */
    } finally {
      setLoggingIn(false);
    }
  };

  const handleLogout = async () => {
    setLoggingOut(true);
    try {
      await postJSON<{ status: string }>(
        `/api/session/${session.gateway_id}/logout`,
        {},
      );
      queryClient.invalidateQueries();
    } catch {
      /* state updated via WebSocket */
    } finally {
      setLoggingOut(false);
    }
  };

  const isBusy =
    loggingIn ||
    loggingOut ||
    session.status === "logging_in" ||
    session.status === "pulling";

  const button = session.user_logged_in ? (
    <button
      onClick={handleLogout}
      disabled={isBusy}
      className="rounded-lg bg-red-100 px-3 py-1.5 text-xs font-semibold text-red-700 transition-colors hover:bg-red-200 disabled:opacity-50 dark:bg-red-900 dark:text-red-200 dark:hover:bg-red-800"
    >
      {loggingOut ? "Logging out…" : compact ? "Logout" : "Logout & Release"}
    </button>
  ) : (
    <button
      onClick={handleLogin}
      disabled={isBusy}
      className="rounded-lg bg-emerald-100 px-3 py-1.5 text-xs font-semibold text-emerald-700 transition-colors hover:bg-emerald-200 disabled:opacity-50 dark:bg-emerald-900 dark:text-emerald-200 dark:hover:bg-emerald-800"
    >
      {isBusy && session.status === "logging_in"
        ? "Awaiting 2FA…"
        : isBusy && session.status === "pulling"
          ? "Pulling data…"
          : loggingIn
            ? "Logging in…"
            : compact
              ? "Pull"
              : "Pull Fresh Data"}
    </button>
  );

  if (compact) {
    return (
      <div className="flex items-center gap-2">
        <span className={`h-2 w-2 rounded-full shrink-0 ${dotClass}`} aria-hidden />
        <span className="text-xs text-slate-500 dark:text-slate-400">{session.label}</span>
        {button}
      </div>
    );
  }

  return (
    <>
      <div className="flex items-center gap-2 min-w-[180px]">
        <span className={`h-2.5 w-2.5 rounded-full shrink-0 ${dotClass}`} aria-hidden />
        <div>
          <p className={`text-sm font-semibold ${textClass}`}>
            <span className="text-slate-400 dark:text-slate-500">{session.label}: </span>
            {session.message}
          </p>
          <p className="text-xs text-slate-400 dark:text-slate-500">
            {session.account_id ? `${session.account_id} · ` : ""}
            checked {checked}
            {session.last_pull && (
              <> · last pull {new Date(session.last_pull).toLocaleTimeString()}</>
            )}
          </p>
        </div>
      </div>
      <div className="flex items-center gap-2">{button}</div>
    </>
  );
}

export function HeaderBar({ sessions }: { sessions: SessionMap }) {
  const { selected, setSelected, accounts, isAll } = useAccount();

  const { data: account } = useQuery({
    queryKey: ["account", selected],
    queryFn: () => getJSON<AccountSummary | null>(withAccount("/api/account", selected)),
    enabled: !isAll,
  });

  const gateways = Object.values(sessions).sort((a, b) =>
    a.gateway_id.localeCompare(b.gateway_id),
  );

  // The gateway that owns the selected account gets the prominent controls; the
  // rest stay compact so any user can still be logged in from any view.
  const selectedGateway = isAll
    ? null
    : gateways.find((g) => g.account_id === selected) ?? null;
  const primary = selectedGateway ?? (gateways.length === 1 ? gateways[0] : null);
  const others = gateways.filter((g) => g !== primary);

  const stats: Record<string, number | null> = {};
  for (const s of STATS) {
    stats[s.key] = isAll
      ? sumStat(accounts, s.key)
      : ((account?.[s.key] as number | null) ?? null);
  }

  // These are account-level totals (net liq, cash, ...) - always in the
  // account's own base currency, never the trade/position currency.
  const selectedCurrency =
    accounts.find((a) => a.account_id === selected)?.base_currency ?? "USD";

  // Summing money across accounts only means something in one currency.
  const currencies = new Set(
    accounts.map((a) => a.base_currency).filter((c): c is string => !!c),
  );
  const mixedCurrency = isAll && currencies.size > 1;

  return (
    <div className="rounded-xl border border-slate-200 bg-white px-5 py-4 shadow-sm dark:border-slate-700 dark:bg-slate-900">
      {/* User switcher */}
      {(accounts.length > 1 || gateways.length > 1) && (
        <div className="mb-3 flex flex-wrap items-center gap-2 border-b border-slate-100 pb-3 dark:border-slate-800">
          <span className="text-xs uppercase tracking-wide text-slate-400 dark:text-slate-500">
            Account
          </span>
          <div className="flex flex-wrap gap-1 rounded-lg bg-slate-100 p-1 dark:bg-slate-800">
            {accounts.map((a) => (
              <button
                key={a.account_id}
                onClick={() => setSelected(a.account_id)}
                className={`rounded-md px-3 py-1 text-xs font-semibold transition-colors ${
                  selected === a.account_id
                    ? "bg-white text-slate-900 shadow-sm dark:bg-slate-600 dark:text-slate-50"
                    : "text-slate-500 hover:text-slate-800 dark:text-slate-400 dark:hover:text-slate-200"
                }`}
                title={a.account_id}
              >
                {a.label}
              </button>
            ))}
            <button
              onClick={() => setSelected(ALL_ACCOUNTS)}
              className={`rounded-md px-3 py-1 text-xs font-semibold transition-colors ${
                isAll
                  ? "bg-white text-slate-900 shadow-sm dark:bg-slate-600 dark:text-slate-50"
                  : "text-slate-500 hover:text-slate-800 dark:text-slate-400 dark:hover:text-slate-200"
              }`}
            >
              All
            </button>
          </div>
          {others.length > 0 && (
            <div className="ml-auto flex flex-wrap items-center gap-3">{
              others.map((g) => (
                <GatewayControls key={g.gateway_id} session={g} compact />
              ))
            }</div>
          )}
        </div>
      )}

      <div className="flex flex-wrap items-center gap-x-6 gap-y-3">
        {primary ? (
          <GatewayControls session={primary} compact={false} />
        ) : (
          <div className="flex items-center gap-2 min-w-[180px]">
            <span className="h-2.5 w-2.5 rounded-full shrink-0 bg-slate-400" aria-hidden />
            <p className="text-sm font-semibold text-slate-500">
              Combined view — pick an account to log in.
            </p>
          </div>
        )}

        {/* Refresh indicators */}
        {primary?.pull_source && (
          <div className="flex items-center gap-2">
            <span
              className={`rounded-full px-2 py-0.5 text-[10px] font-semibold uppercase ${SOURCE_BADGE[primary.pull_source] ?? SOURCE_BADGE.cache}`}
            >
              {SOURCE_LABEL[primary.pull_source] ?? primary.pull_source}
            </span>
            {account?.source && (
              <span
                className={`rounded-full px-2 py-0.5 text-[10px] font-semibold uppercase ${SOURCE_BADGE[account.source] ?? SOURCE_BADGE.cache}`}
              >
                acct: {SOURCE_LABEL[account.source] ?? account.source}
              </span>
            )}
          </div>
        )}

        {/* Divider */}
        <div className="hidden h-8 w-px bg-slate-200 sm:block dark:bg-slate-700" aria-hidden />

        {/* Account stats */}
        <div className="flex flex-wrap gap-x-6 gap-y-2">
          {STATS.map((s) => (
            <div key={s.key}>
              <p className="text-xs uppercase tracking-wide text-slate-400 dark:text-slate-500">
                {s.label}
              </p>
              <p className="mt-0.5 text-sm font-semibold text-slate-800 dark:text-slate-50">
                {mixedCurrency
                  ? "—"
                  : money(
                      stats[s.key],
                      isAll ? (currencies.values().next().value ?? "USD") : selectedCurrency,
                    )}
              </p>
            </div>
          ))}
        </div>
      </div>

      {/* Per-user breakdown behind the combined tiles. */}
      {isAll && accounts.length > 1 && (
        <div className="mt-3 flex flex-wrap gap-x-6 gap-y-1 border-t border-slate-100 pt-3 text-xs dark:border-slate-800">
          {mixedCurrency && (
            <span className="text-amber-600 dark:text-amber-400">
              Accounts use different base currencies — totals not summed.
            </span>
          )}
          {accounts.map((a) => (
            <span key={a.account_id} className="text-slate-400 dark:text-slate-500">
              {a.label}:{" "}
              <span className="font-semibold text-slate-600 dark:text-slate-300">
                {money(a.net_liquidation, a.base_currency ?? "USD")}
              </span>
            </span>
          ))}
        </div>
      )}
    </div>
  );
}
