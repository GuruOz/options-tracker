import { useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { getJSON, postJSON } from "../api/client";
import type { AccountSummary, PullResult, SessionState } from "../api/types";

const money = (v: number | null | undefined) =>
  v == null
    ? "—"
    : v.toLocaleString(undefined, {
        style: "currency",
        currency: "USD",
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

export function HeaderBar({ session }: { session: SessionState }) {
  const [loggingIn, setLoggingIn] = useState(false);
  const [loggingOut, setLoggingOut] = useState(false);
  const queryClient = useQueryClient();

  const { data: account } = useQuery({
    queryKey: ["account"],
    queryFn: () => getJSON<AccountSummary | null>("/api/account"),
  });

  const dotClass = STATUS_DOT[session.status] ?? STATUS_DOT.unknown;
  const textClass = STATUS_TEXT[session.status] ?? STATUS_TEXT.unknown;
  const checked = session.last_checked
    ? new Date(session.last_checked).toLocaleTimeString()
    : "—";

  const handleLogin = async () => {
    setLoggingIn(true);
    try {
      const result = await postJSON<PullResult>("/api/session/login", {});
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
      await postJSON<{ status: string }>("/api/session/logout", {});
      queryClient.invalidateQueries();
    } catch {
      /* state updated via WebSocket */
    } finally {
      setLoggingOut(false);
    }
  };

  const isBusy = loggingIn || loggingOut || session.status === "logging_in" || session.status === "pulling";
  const isLoggedIn = session.user_logged_in;

  return (
    <div className="rounded-xl border border-slate-200 bg-white px-5 py-4 shadow-sm dark:border-slate-700 dark:bg-slate-900">
      <div className="flex flex-wrap items-center gap-x-6 gap-y-3">
        {/* Connection status */}
        <div className="flex items-center gap-2 min-w-[180px]">
          <span className={`h-2.5 w-2.5 rounded-full shrink-0 ${dotClass}`} aria-hidden />
          <div>
            <p className={`text-sm font-semibold ${textClass}`}>{session.message}</p>
            <p className="text-xs text-slate-400 dark:text-slate-500">
              {session.account_id ? `${session.account_id} · ` : ""}
              checked {checked}
              {session.last_pull && (
                <> · last pull {new Date(session.last_pull).toLocaleTimeString()}</>
              )}
            </p>
          </div>
        </div>

        {/* Login/Logout */}
        <div className="flex items-center gap-2">
          {isLoggedIn ? (
            <button
              onClick={handleLogout}
              disabled={isBusy}
              className="rounded-lg bg-red-100 px-3 py-1.5 text-xs font-semibold text-red-700 transition-colors hover:bg-red-200 disabled:opacity-50 dark:bg-red-900 dark:text-red-200 dark:hover:bg-red-800"
            >
              {loggingOut ? "Logging out…" : "Logout & Release"}
            </button>
          ) : (
            <button
              onClick={handleLogin}
              disabled={isBusy}
              className="rounded-lg bg-emerald-100 px-3 py-1.5 text-xs font-semibold text-emerald-700 transition-colors hover:bg-emerald-200 disabled:opacity-50 dark:bg-emerald-900 dark:text-emerald-200 dark:hover:bg-emerald-800"
            >
              {isBusy && session.status === "logging_in" ? "Awaiting 2FA…" :
               isBusy && session.status === "pulling" ? "Pulling data…" :
               loggingIn ? "Logging in…" :
               "Pull Fresh Data"}
            </button>
          )}
        </div>

        {/* Refresh indicators */}
        {session.pull_source && (
          <div className="flex items-center gap-2">
            <span className={`rounded-full px-2 py-0.5 text-[10px] font-semibold uppercase ${SOURCE_BADGE[session.pull_source] ?? SOURCE_BADGE.cache}`}>
              {SOURCE_LABEL[session.pull_source] ?? session.pull_source}
            </span>
            {account?.source && (
              <span className={`rounded-full px-2 py-0.5 text-[10px] font-semibold uppercase ${SOURCE_BADGE[account.source] ?? SOURCE_BADGE.cache}`}>
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
              <p className="text-xs uppercase tracking-wide text-slate-400 dark:text-slate-500">{s.label}</p>
              <p className="mt-0.5 text-sm font-semibold text-slate-800 dark:text-slate-50">
                {money(account?.[s.key] as number | null)}
              </p>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
