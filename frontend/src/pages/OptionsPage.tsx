import { useState } from "react";
import { useSession } from "../api/useSession";
import { HeaderBar } from "../components/HeaderBar";
import { UnderlyingsPanel } from "../components/UnderlyingsPanel";
import { SignalPanel } from "../components/SignalPanel";
import { AlertsPanel } from "../components/AlertsPanel";
import { PositionsPanel } from "../components/PositionsPanel";
import { DecayPanel } from "../components/DecayPanel";
import { ProfitPanel } from "../components/ProfitPanel";
import { RiskPanel } from "../components/RiskPanel";
import { IncomePanel } from "../components/IncomePanel";
import { MarketContextPanel } from "../components/MarketContextPanel";

/** The original options-selling dashboard, unchanged — now its own route. */
export function OptionsPage() {
  const sessions = useSession();
  // Which position the decay & profit panels chart; driven by clicking a row in PositionsPanel.
  const [selectedConid, setSelectedConid] = useState<number | null>(null);

  return (
    <div>
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
    </div>
  );
}
