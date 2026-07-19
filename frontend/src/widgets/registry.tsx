import type { Layout } from "react-grid-layout";
import {
  AiSuggestions,
  AllocationDonut,
  CustomChart,
  EndowusHoldings,
  FireProgress,
  NetWorthHero,
  NetWorthTrend,
  OptionsSnapshot,
  SavingsRate,
  SourceCard,
  StatementStaleness,
} from "./widgets";

export interface WidgetConfigField {
  key: string;
  label: string;
  type: "select" | "number";
  options?: { value: string; label: string }[];
  min?: number;
  max?: number;
}

export interface WidgetDef {
  type: string;
  title: string;
  description: string;
  defaultW: number;
  defaultH: number;
  minW: number;
  minH: number;
  configSchema?: WidgetConfigField[];
  component: React.ComponentType<{ config: Record<string, unknown> }>;
}

/** One placed widget on the dashboard. */
export interface WidgetItem {
  i: string; // unique instance id
  type: string;
  config: Record<string, unknown>;
  x: number;
  y: number;
  w: number;
  h: number;
}

const MONTHS_OPTS = [
  { value: "12", label: "12 months" },
  { value: "24", label: "24 months" },
  { value: "36", label: "36 months" },
];

export const WIDGETS: Record<string, WidgetDef> = {
  "networth-hero": {
    type: "networth-hero",
    title: "Net worth",
    description: "Total net worth, month-over-month change, and each person's figure.",
    defaultW: 6, defaultH: 3, minW: 3, minH: 2,
    component: NetWorthHero,
  },
  "source-card": {
    type: "source-card",
    title: "Source",
    description: "One source (IBKR / CPF / Endowus) with its sub-totals.",
    defaultW: 3, defaultH: 3, minW: 2, minH: 2,
    component: SourceCard,
    configSchema: [
      {
        key: "source", label: "Source", type: "select",
        options: [
          { value: "ibkr", label: "IBKR" },
          { value: "cpf", label: "CPF" },
          { value: "endowus", label: "Endowus" },
        ],
      },
    ],
  },
  "allocation-donut": {
    type: "allocation-donut",
    title: "Allocation",
    description: "Donut of where the money sits, by source or asset class.",
    defaultW: 4, defaultH: 4, minW: 3, minH: 3,
    component: AllocationDonut,
    configSchema: [
      {
        key: "groupBy", label: "Group by", type: "select",
        options: [
          { value: "source", label: "Source" },
          { value: "asset", label: "Asset class" },
        ],
      },
    ],
  },
  "networth-trend": {
    type: "networth-trend",
    title: "Net worth trend",
    description: "Stacked area of net worth over time, by source.",
    defaultW: 8, defaultH: 4, minW: 4, minH: 3,
    component: NetWorthTrend,
    configSchema: [{ key: "months", label: "Range", type: "select", options: MONTHS_OPTS }],
  },
  "endowus-holdings": {
    type: "endowus-holdings",
    title: "Endowus holdings",
    description: "Top funds with value and allocation.",
    defaultW: 4, defaultH: 4, minW: 3, minH: 2,
    component: EndowusHoldings,
  },
  "statement-staleness": {
    type: "statement-staleness",
    title: "Statement reminders",
    description: "Flags CPF/Endowus statements older than 40 days.",
    defaultW: 4, defaultH: 2, minW: 3, minH: 2,
    component: StatementStaleness,
  },
  "options-snapshot": {
    type: "options-snapshot",
    title: "Options",
    description: "Open positions and this month's premium; links to the options tracker.",
    defaultW: 4, defaultH: 2, minW: 3, minH: 2,
    component: OptionsSnapshot,
  },
  "fire-progress": {
    type: "fire-progress",
    title: "FIRE progress",
    description: "Progress toward your FIRE number with an on-track verdict.",
    defaultW: 4, defaultH: 2, minW: 3, minH: 2,
    component: FireProgress,
  },
  "savings-rate": {
    type: "savings-rate",
    title: "Savings rate",
    description: "This month's savings rate with a 6-month sparkline.",
    defaultW: 4, defaultH: 2, minW: 3, minH: 2,
    component: SavingsRate,
  },
  "ai-suggestions": {
    type: "ai-suggestions",
    title: "AI suggestions",
    description: "Latest AI-generated suggested moves, with a Generate button.",
    defaultW: 6, defaultH: 4, minW: 3, minH: 3,
    component: AiSuggestions,
  },
  "custom-chart": {
    type: "custom-chart",
    title: "Custom chart",
    description: "Pick a metric and chart type — build your own view of the data.",
    defaultW: 6, defaultH: 4, minW: 3, minH: 3,
    component: CustomChart,
    configSchema: [
      {
        key: "metric", label: "Metric", type: "select",
        options: [
          { value: "networth_total", label: "Net worth (total)" },
          { value: "networth_by_source", label: "Net worth by source" },
          { value: "premium_income", label: "Options premium / month" },
          { value: "savings", label: "Monthly savings" },
        ],
      },
      {
        key: "chartType", label: "Chart", type: "select",
        options: [
          { value: "area", label: "Area" },
          { value: "line", label: "Line" },
          { value: "bar", label: "Bar" },
        ],
      },
      { key: "months", label: "Range", type: "select", options: MONTHS_OPTS },
    ],
  },
};

let _seq = 0;
export function newItem(type: string): WidgetItem {
  const def = WIDGETS[type];
  const config: Record<string, unknown> = {};
  for (const f of def.configSchema ?? []) {
    if (f.type === "select" && f.options?.length) config[f.key] = f.options[0].value;
  }
  return {
    i: `${type}-${Date.now()}-${_seq++}`,
    type,
    config,
    x: 0,
    y: Infinity, // append at the bottom
    w: def.defaultW,
    h: def.defaultH,
  };
}

/** Sensible starting dashboard when a scope has no saved layout. */
export function defaultLayout(): WidgetItem[] {
  const place = (type: string, x: number, y: number): WidgetItem => {
    const def = WIDGETS[type];
    return { i: `${type}-default`, type, config: seedConfig(type), x, y, w: def.defaultW, h: def.defaultH };
  };
  return [
    place("networth-hero", 0, 0),
    { ...place("allocation-donut", 6, 0), config: { groupBy: "source" } },
    { ...place("networth-trend", 0, 3), config: { months: 24 } },
    { ...place("source-card", 8, 3), config: { source: "cpf" } },
    place("endowus-holdings", 0, 7),
    place("statement-staleness", 4, 7),
    place("options-snapshot", 8, 7),
  ];
}

function seedConfig(type: string): Record<string, unknown> {
  const config: Record<string, unknown> = {};
  for (const f of WIDGETS[type].configSchema ?? []) {
    if (f.type === "select" && f.options?.length) config[f.key] = f.options[0].value;
  }
  return config;
}

/** Convert widget items <-> react-grid-layout Layout[]. */
export function toGridLayout(items: WidgetItem[]): Layout[] {
  return items.map((it) => {
    const def = WIDGETS[it.type];
    return { i: it.i, x: it.x, y: it.y === Infinity ? 0 : it.y, w: it.w, h: it.h, minW: def?.minW, minH: def?.minH };
  });
}
