import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { getJSON } from "./api/client";
import { useSession } from "./api/useSession";
import { AccountProvider } from "./hooks/useAccount";
import { useTheme } from "./hooks/useTheme";
import type { Meta } from "./api/types";
import { HeaderBar } from "./components/HeaderBar";
import { UnderlyingsPanel } from "./components/UnderlyingsPanel";
import { SignalPanel } from "./components/SignalPanel";
import { AlertsPanel } from "./components/AlertsPanel";
import { PositionsPanel } from "./components/PositionsPanel";
import { DecayPanel } from "./components/DecayPanel";
import { ProfitPanel } from "./components/ProfitPanel";
import { RiskPanel } from "./components/RiskPanel";
import { IncomePanel } from "./components/IncomePanel";
import { MarketContextPanel } from "./components/MarketContextPanel";

export default function App() {
  return (
    <AccountProvider>
      <Dashboard />
    </AccountProvider>
  );
}

function Dashboard() {
  const sessions = useSession();
  const { theme, toggleTheme } = useTheme();
  // Which position the decay & profit panels chart; driven by clicking a row in PositionsPanel.
  const [selectedConid, setSelectedConid] = useState<number | null>(null);
  const { data: meta } = useQuery({
    queryKey: ["meta"],
    queryFn: () => getJSON<Meta>("/api/meta"),
  });

  return (
    <div className="mx-auto max-w-7xl px-4 py-6 md:px-8">
      <header className="mb-5 flex flex-wrap items-baseline justify-between gap-2">
        <div>
          <h1 className="text-2xl font-bold text-slate-900 dark:text-slate-50">Options Tracker</h1>
          <p className="text-sm text-slate-500 dark:text-slate-400">
            Read-only options-selling dashboard{meta ? ` · v${meta.version}` : ""}
          </p>
        </div>
        <button
          onClick={toggleTheme}
          className="rounded-lg bg-slate-200 p-2 text-slate-900 transition-colors hover:bg-slate-300 dark:bg-slate-700 dark:text-slate-100 dark:hover:bg-slate-600"
          title={`Switch to ${theme === "dark" ? "light" : "dark"} mode`}
        >
          {theme === "dark" ? "☀️" : "🌙"}
        </button>
      </header>

      <div className="mb-6">
        <HeaderBar sessions={sessions} />
      </div>

      <div className="space-y-4">
        <UnderlyingsPanel />
        <SignalPanel />
        <AlertsPanel />
        <PositionsPanel selectedConid={selectedConid} onSelect={setSelectedConid} />
        <DecayPanel selectedConid={selectedConid} onSelect={setSelectedConid} />
        <ProfitPanel selectedConid={selectedConid} onSelect={setSelectedConid} />
        <RiskPanel />
        <IncomePanel />
        <MarketContextPanel />
      </div>

      {meta?.disclaimer && (
        <footer className="mt-8 border-t border-slate-200 pt-4 text-xs text-slate-400 dark:border-slate-700 dark:text-slate-500">
          {meta.disclaimer}
        </footer>
      )}
    </div>
  );
}
