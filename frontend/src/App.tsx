import { useQuery } from "@tanstack/react-query";
import { getJSON } from "./api/client";
import { useSession } from "./api/useSession";
import type { Meta } from "./api/types";
import { HeaderBar } from "./components/HeaderBar";
import { UnderlyingsPanel } from "./components/UnderlyingsPanel";
import { SignalPanel } from "./components/SignalPanel";
import { PositionsPanel } from "./components/PositionsPanel";
import { MarketPanel } from "./components/MarketPanel";
import { PanelGrid } from "./components/PanelGrid";

export default function App() {
  const session = useSession();
  const { data: meta } = useQuery({
    queryKey: ["meta"],
    queryFn: () => getJSON<Meta>("/api/meta"),
  });

  return (
    <div className="mx-auto max-w-7xl px-4 py-6 md:px-8">
      <header className="mb-5 flex flex-wrap items-baseline justify-between gap-2">
        <div>
          <h1 className="text-2xl font-bold text-slate-900">Options Tracker</h1>
          <p className="text-sm text-slate-500">
            Read-only options-selling dashboard{meta ? ` · v${meta.version}` : ""}
          </p>
        </div>
      </header>

      <div className="mb-6">
        <HeaderBar session={session} />
      </div>

      <div className="space-y-4">
        <UnderlyingsPanel />
        <SignalPanel />
        <PositionsPanel />
        <MarketPanel />
      </div>

      <h2 className="mb-3 mt-8 text-lg font-semibold text-slate-700">
        Analytics <span className="text-sm font-normal text-slate-400">— coming next</span>
      </h2>
      <PanelGrid />

      {meta?.disclaimer && (
        <footer className="mt-8 border-t border-slate-200 pt-4 text-xs text-slate-400">
          {meta.disclaimer}
        </footer>
      )}
    </div>
  );
}
