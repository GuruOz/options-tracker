export type GatewayStatus =
  | "unknown"
  | "disconnected"
  | "authenticated"
  | "pulling"
  | "logging_in";

export interface SessionState {
  status: GatewayStatus;
  authenticated: boolean;
  connected: boolean;
  competing: boolean;
  account_id: string | null;
  message: string;
  last_checked: string | null;
  user_logged_in: boolean;
  last_pull: string | null;
  pull_source: string | null;
  login_requested_at: string | null;
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
  dte: number | null;
  underlying_price: number | null;
  premium_captured_pct: number | null;
  cushion_pct: number | null;
  breakeven: number | null;
  breakeven_cushion_pct: number | null;
  intrinsic_value: number | null;
  extrinsic_value: number | null;
  decay_curve: DecayPoint[] | null;
  status: string | null;
  chain_id: string | null;
  source: string | null;
  last_updated: string | null;
}

export interface DecayPoint {
  dte: number;
  extrinsic: number;
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
  source: string | null;
  last_updated: string | null;
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
  source: string | null;
}

export interface MarketHistoryPoint {
  date: string; // "YYYY-MM-DD"
  close: number | null;
  sma: number | null;
  sma200: number | null;
  vix: number | null;
}

export interface MarketHistory {
  conid: number;
  symbol: string | null;
  months: number;
  sma_window: number;
  points: MarketHistoryPoint[];
  market: Market | null;
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
  source: string | null;
}

export interface SignalPoint {
  ts: string | null;
  composite_score: number | null;
  verdict: string | null;
}

export interface PullResult {
  status: string;
  account_id?: string;
  pull_ts?: string;
  positions?: string;
  account?: string;
  trades?: string;
  market?: string;
  message?: string;
}

export interface Trade {
  exec_id: string;
  conid: number | null;
  symbol: string | null;
  sec_type: string | null;
  side: string | null;
  right: string | null;
  strike: number | null;
  expiry: string | null;
  qty: number | null;
  price: number | null;
  commission: number | null;
  exec_time: string | null;
}

export interface RiskPosition {
  symbol: string | null;
  sec_type: string | null;
  right: string | null;
  strike: number | null;
  beta: number | null;
  delta_dollars: number | null;
  beta_weighted_delta_dollars: number | null;
  scenario_pnl: number | null;
}

export interface Assignment {
  total_obligation: number | null;
  cash: number | null;
  coverage_ratio: number | null;
  short_put_count: number;
}

export interface EquityPoint {
  ts: string | null;
  net_liquidation: number | null;
}

export interface RollChainLeg {
  leg_id: string;
  exec_id: string | null;
  role: string;
  date: string | null;
  action: string | null;
  strike: number | null;
  price: number;
  credit: number;
  qty?: number | null;
}

export interface RollChain {
  chain_id: string;
  underlying_symbol: string | null;
  right: string | null;
  strike: number | null;
  status: string | null;
  close_reason?: string | null;
  opened_at: string | null;
  closed_at: string | null;
  cumulative_credit: number | null;
  leg_count: number;
  conids: number[];
  legs?: RollChainLeg[];
}

export interface Risk {
  scenario_move: number;
  index_symbol: string | null;
  net_liquidation: number | null;
  beta_weighted_delta_dollars: number | null;
  gross_delta_dollars: number | null;
  scenario_pnl: number | null;
  scenario_pnl_pct: number | null;
  assignment: Assignment;
  positions: RiskPosition[];
  equity_curve: EquityPoint[];
}

export interface IncomeMonth {
  month: string; // "YYYY-MM"
  pnl: number;
  chain_count: number;
  cashed_out: boolean;
  withdrawal: number | null;
  note: string | null;
}

export interface IncomeYear {
  year: number;
  ytd: number;
  withdrawn: number;
  remaining: number;
}

export interface Income {
  months: IncomeMonth[];
  years: IncomeYear[];
  all_time: number;
  realized: number;
  unrealized: number;
  win_rate: number | null;
  closed_count: number;
  open_count: number;
  net_liquidation: number | null;
  yield_pct: number | null;
}
