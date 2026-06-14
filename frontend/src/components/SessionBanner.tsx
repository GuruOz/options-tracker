import type { SessionState } from "../api/types";

const STYLES: Record<string, string> = {
  authenticated: "bg-emerald-50 border-emerald-300 text-emerald-900",
  polling: "bg-emerald-50 border-emerald-300 text-emerald-900",
  disconnected: "bg-amber-50 border-amber-300 text-amber-900",
  unknown: "bg-slate-100 border-slate-300 text-slate-700",
};

export function SessionBanner({ session }: { session: SessionState }) {
  const tone = STYLES[session.status] ?? STYLES.unknown;
  const live = session.authenticated;
  const checked = session.last_checked
    ? new Date(session.last_checked).toLocaleTimeString()
    : "—";

  return (
    <div className={`flex items-center gap-3 rounded-lg border px-4 py-3 ${tone}`}>
      <span
        className={`inline-block h-2.5 w-2.5 rounded-full ${
          live ? "bg-emerald-500" : "bg-amber-500"
        }`}
        aria-hidden
      />
      <div className="flex-1">
        <p className="text-sm font-medium">{session.message}</p>
        <p className="text-xs opacity-70">
          {session.account_id ? `Account ${session.account_id} · ` : ""}
          last checked {checked}
        </p>
      </div>
      <span className="text-xs font-semibold uppercase tracking-wide">
        {session.status}
      </span>
    </div>
  );
}
