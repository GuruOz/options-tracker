export type GatewayStatus =
  | "unknown"
  | "disconnected"
  | "authenticated"
  | "polling";

export interface SessionState {
  status: GatewayStatus;
  authenticated: boolean;
  connected: boolean;
  competing: boolean;
  account_id: string | null;
  message: string;
  last_checked: string | null;
}

export interface Meta {
  version: string;
  disclaimer: string;
}

export interface Position {
  conid: number;
  symbol: string | null;
  sec_type: string | null;
  right: string | null;
  strike: number | null;
  expiry: string | null;
  position: number | null;
  avg_cost: number | null;
  mark: number | null;
  market_value: number | null;
  unrealized_pnl: number | null;
  delta: number | null;
  gamma: number | null;
  theta: number | null;
  vega: number | null;
  iv: number | null;
  greeks_source: string | null;
  snapshot_ts: string | null;
}

export interface AccountSummary {
  snapshot_ts: string | null;
  net_liquidation: number | null;
  available_funds: number | null;
  excess_liquidity: number | null;
  maintenance_margin: number | null;
  buying_power: number | null;
  cash: number | null;
  leverage: number | null;
}

export interface Market {
  conid: number;
  symbol: string | null;
  snapshot_ts: string | null;
  price: number | null;
  iv: number | null;
  realized_vol: number | null;
  iv_percentile: number | null;
  iv_rank: number | null;
  rsi14: number | null;
  sma50: number | null;
  sma200: number | null;
}

export interface SignalSubScores {
  iv_percentile: number | null;
  variance_premium: number | null;
  trend: number | null;
  rsi_drawdown: number | null;
}

export interface ContractResult {
  conid: number;
  symbol: string;
  description: string;
}

export interface Signal {
  underlying_conid: number;
  symbol: string | null;
  ts: string | null;
  composite_score: number | null;
  verdict: string | null;
  sub_scores: SignalSubScores | null;
}
