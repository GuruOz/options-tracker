import { NavLink, Outlet, useLocation } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { getJSON } from "../api/client";
import type { Meta } from "../api/types";
import { useAuth } from "../hooks/useAuth";
import { useTheme } from "../hooks/useTheme";
import { ALL_OWNERS, useScope } from "../hooks/useScope";
import { useDisplayCurrency } from "../hooks/useDisplayCurrency";

const NAV = [
  { to: "/", label: "Home", end: true },
  { to: "/networth", label: "Net Worth", end: false },
  { to: "/options", label: "Options", end: false },
  { to: "/plan", label: "Plan", end: false },
  { to: "/uploads", label: "Uploads", end: false },
  { to: "/settings", label: "Settings", end: false },
];

/** Pages that scope by owner + display currency (Options has its own switcher). */
const SCOPED_ROUTES = new Set(["/", "/networth", "/plan"]);

function Pill({
  active,
  children,
  onClick,
  title,
}: {
  active: boolean;
  children: React.ReactNode;
  onClick: () => void;
  title?: string;
}) {
  return (
    <button
      onClick={onClick}
      title={title}
      className={`rounded-md px-3 py-1 text-xs font-semibold transition-colors ${
        active
          ? "bg-white text-slate-900 shadow-sm dark:bg-slate-600 dark:text-slate-50"
          : "text-slate-500 hover:text-slate-800 dark:text-slate-400 dark:hover:text-slate-200"
      }`}
    >
      {children}
    </button>
  );
}

function ScopeBar() {
  const { selected, setSelected, owners } = useScope();
  const { currency, setCurrency, options } = useDisplayCurrency();

  if (owners.length <= 1) return null;

  return (
    <div className="mx-auto flex max-w-7xl flex-wrap items-center gap-2 px-4 py-2 md:px-8">
      <span className="text-xs uppercase tracking-wide text-slate-400 dark:text-slate-500">
        Whose
      </span>
      <div className="flex flex-wrap gap-1 rounded-lg bg-slate-100 p-1 dark:bg-slate-800">
        {owners.map((o) => (
          <Pill
            key={o.owner}
            active={selected === o.owner}
            onClick={() => setSelected(o.owner)}
            title={o.owner}
          >
            {o.label}
          </Pill>
        ))}
        <Pill active={selected === ALL_OWNERS} onClick={() => setSelected(ALL_OWNERS)}>
          Combined
        </Pill>
      </div>
      {options.length > 1 && (
        <div
          className="flex flex-wrap gap-1 rounded-lg bg-slate-100 p-1 dark:bg-slate-800"
          title="Currency the combined household figures are converted into (live FX)."
        >
          {options.map((c) => (
            <Pill key={c} active={currency === c} onClick={() => setCurrency(c)}>
              {c}
            </Pill>
          ))}
        </div>
      )}
    </div>
  );
}

export function AppLayout() {
  const { logout } = useAuth();
  const { theme, toggleTheme } = useTheme();
  const { pathname } = useLocation();
  const { data: meta } = useQuery({
    queryKey: ["meta"],
    queryFn: () => getJSON<Meta>("/api/meta"),
  });

  return (
    <div className="min-h-screen bg-slate-50 dark:bg-slate-950">
      <header className="border-b border-slate-200 bg-white dark:border-slate-800 dark:bg-slate-900">
        <div className="mx-auto flex max-w-7xl flex-wrap items-center gap-x-4 gap-y-2 px-4 py-3 md:px-8">
          <span className="text-lg font-bold text-slate-900 dark:text-slate-50">
            Finance
          </span>
          <nav className="flex flex-wrap gap-1">
            {NAV.map((item) => (
              <NavLink
                key={item.to}
                to={item.to}
                end={item.end}
                className={({ isActive }) =>
                  `rounded-md px-3 py-1.5 text-sm font-semibold transition-colors ${
                    isActive
                      ? "bg-slate-100 text-slate-900 dark:bg-slate-800 dark:text-slate-50"
                      : "text-slate-500 hover:text-slate-800 dark:text-slate-400 dark:hover:text-slate-200"
                  }`
                }
              >
                {item.label}
              </NavLink>
            ))}
          </nav>
          <div className="ml-auto flex items-center gap-2">
            <button
              onClick={toggleTheme}
              className="rounded-lg bg-slate-200 p-2 text-slate-900 transition-colors hover:bg-slate-300 dark:bg-slate-700 dark:text-slate-100 dark:hover:bg-slate-600"
              title={`Switch to ${theme === "dark" ? "light" : "dark"} mode`}
            >
              {theme === "dark" ? "☀️" : "🌙"}
            </button>
            <button
              onClick={() => logout()}
              className="rounded-lg bg-slate-200 px-3 py-2 text-xs font-semibold text-slate-900 transition-colors hover:bg-slate-300 dark:bg-slate-700 dark:text-slate-100 dark:hover:bg-slate-600"
              title="Log out"
            >
              Logout
            </button>
          </div>
        </div>
        {SCOPED_ROUTES.has(pathname) && (
          <div className="border-t border-slate-100 dark:border-slate-800">
            <ScopeBar />
          </div>
        )}
      </header>

      <main className="mx-auto max-w-7xl px-4 py-6 md:px-8">
        <Outlet />
      </main>

      {meta?.disclaimer && (
        <footer className="mx-auto max-w-7xl border-t border-slate-200 px-4 py-4 text-xs text-slate-400 dark:border-slate-700 dark:text-slate-500 md:px-8">
          {meta.disclaimer}
        </footer>
      )}
    </div>
  );
}
