export type GatewayStatus =
  | "unknown"
  | "disconnected"
  | "authenticated"
  | "pulling"
  | "logging_in";

export interface SessionState {
  gateway_id: string;
  label: string;
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

/** Every declared user's session, keyed by gateway id ("user1", "user2", ...). */
export type SessionMap = Record<string, SessionState>;

/** An account plus its latest summary — one entry per user in the switcher. */
export interface AccountInfo {
  account_id: string;
  label: string;
  base_currency: string | null;
  gateway_id: string | null;
  snapshot_ts: string | null;
  net_liquidation: number | null;
  available_funds: number | null;
  excess_liquidity: number | null;
  maintenance_margin: number | null;
  buying_power: number | null;
  cash: number | null;
  leverage: number | null;
  source: string | null;
}

export interface Meta {
  version: string;
  disclaimer: string;
}

// --- Finance-tracker (net worth / owners) ---

export type AccountKind = "ibkr" | "cpf" | "endowus";

export interface OwnerAccount {
  account_id: string;
  kind: AccountKind;
  label: string;
}

export interface OwnerInfo {
  owner: string;
  label: string;
  accounts: OwnerAccount[];
}

export interface OwnersResponse {
  owners: OwnerInfo[];
}

/** One net-worth source (ibkr/cpf/endowus) for one owner. */
export interface NetWorthSource {
  value: number | null; // native when a single currency, else = converted
  currency: string;
  converted: number | null; // always in the requested target, when resolvable
  as_of: string | null;
  breakdown?: Record<string, number>; // CPF: OA/SA/MA
  by_funding_source?: Record<string, number>; // Endowus
  by_asset_class?: Record<string, number>; // Endowus
}

export interface NetWorthOwner {
  owner: string;
  label: string;
  total_converted: number | null;
  sources: Partial<Record<AccountKind, NetWorthSource>>;
}

export interface NetWorthResponse {
  as_of_generated: string;
  target_currency: string;
  owners: NetWorthOwner[];
  combined: { total_converted: number | null };
}

// --- Statement uploads ---

export type StatementSource = "cpf" | "endowus";

export interface StatementSummary {
  balances: number;
  transactions: number;
  holdings: number;
  warnings: string[];
}

export interface StatementUploadResult {
  status: "ok" | "duplicate" | "error";
  message?: string;
  account_id?: string;
  period?: [string | null, string | null];
  balances?: number;
  transactions?: number;
  holdings?: number;
  warnings?: string[];
}

export interface StatementLogEntry {
  id: number;
  account_id: string;
  source: StatementSource;
  filename: string | null;
  period_start: string | null;
  period_end: string | null;
  uploaded_at: string | null;
  summary: StatementSummary | null;
}

export interface StatementsResponse {
  statements: StatementLogEntry[];
}

// --- Net-worth history + holdings ---

export interface NetWorthHistoryPoint {
  month: string; // "YYYY-MM-01"
  ibkr: number;
  cpf: number;
  endowus: number;
  total: number;
}

export interface NetWorthHistoryResponse {
  target_currency: string;
  series: NetWorthHistoryPoint[];
}

export interface HoldingRow {
  account_id: string;
  owner: string | null;
  goal_name: string | null;
  fund_name: string | null;
  asset_class: string | null;
  funding_source: string | null;
  units: number | null;
  nav: number | null;
  market_value: number | null;
  converted: number | null;
  allocation_pct: number | null;
  currency: string;
  as_of: string | null;
}

export interface HoldingsResponse {
  target_currency: string;
  holdings: HoldingRow[];
  goal_totals: Record<string, number>;
}

// --- FIRE plan + cashflow ---

export interface PlanSettings {
  current_age: number;
  retire_age: number;
  target_monthly_income: number;
  swr_pct: number;
  expected_return_pct: number;
  pessimistic_return_pct: number;
  optimistic_return_pct: number;
  inflation_pct: number;
  monthly_savings_override: number | null;
}

export interface PlanSettingsResponse {
  owner: string;
  data: PlanSettings;
}

export interface CashflowEntry {
  month: string; // "YYYY-MM-01"
  income: number | null;
  expenses: number | null;
  note: string | null;
}

export interface CashflowResponse {
  owner: string;
  entries: CashflowEntry[];
}

// --- AI advisor ---

export interface AdvisorConfig {
  provider: string | null;
  model: string | null;
  base_url: string | null;
  key_set: boolean;
}

export interface AdvisorSuggestion {
  id?: number;
  created_at?: string | null;
  content?: string;
  model?: string | null;
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
  // The contract's own trading currency, not the account's base currency.
  currency: string | null;
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
  // Chain-level capture for a position inside a roll chain: what unwinding the
  // whole chain nets today, against the premium its cycle is working toward.
  // Null when the position isn't part of a chain.
  chain_captured_pct: number | null;
  chain_profit_if_closed: number | null;
  chain_initial_credit: number | null;
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
  // Which user owns this row — the combined view mixes accounts.
  account_id: string | null;
  account_label: string | null;
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
  // The contract's own trading currency, not the account's base currency.
  currency: string | null;
  exec_time: string | null;
  account_id: string | null;
  account_label: string | null;
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
  expiry: string | null;
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
  // Credit locked in the short leg that's open right now (0 once flat), and the
  // rest of the chain's credit, which is actually banked. A roll only realizes
  // the decay on the leg it replaces, so `banked_credit` is what's collectable
  // to date; the open leg's premium lands only if it expires or is bought back.
  open_credit: number | null;
  banked_credit: number | null;
  initial_credit: number | null;
  leg_count: number;
  conids: number[];
  legs?: RollChainLeg[];
  account_id?: string;
  account_label?: string;
}

// A live FX rate used somewhere in a response, for provenance captions.
export interface FxRateInfo {
  pair: string; // "USD/SGD"
  rate: number;
  as_of: string | null;
  source: string; // "ibkr" | "public" | "cache" | "identity"
}

// GET /api/fx?target=... — one rate per account base currency into `target`.
export interface FxResponse {
  target: string;
  rates: (FxRateInfo & { currency: string })[];
}

export interface Risk {
  scenario_move: number;
  index_symbol: string | null;
  net_liquidation: number | null;
  beta_weighted_delta_dollars: number | null;
  gross_delta_dollars: number | null;
  scenario_pnl: number | null;
  scenario_pnl_pct: number | null;
  // True when a position's currency differs from the account's base currency
  // (or, combined, when accounts disagree). Ratios are converted through a
  // live FX rate when one is available and null only when it isn't.
  currency_mismatch: boolean;
  // The common currency of the dollar figures above, when unambiguous.
  exposure_currency: string | null;
  base_currency?: string | null;
  // Combined view only: the currency everything was converted into (null when
  // no conversion happened or a rate was missing).
  display_currency?: string | null;
  fx_rates?: FxRateInfo[];
  assignment: Assignment;
  positions: RiskPosition[];
  equity_curve: EquityPoint[];
  // Present only in the combined view: each account's own risk, since equity
  // curves can't be summed (their snapshots land on different timestamps) and
  // assignment coverage pools cash that isn't fungible across accounts.
  per_account?: (Risk & { account_id: string; account_label: string })[];
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
  // Despite the name, this is what open chains have *banked* from rolling — the
  // premium locked in their open legs is excluded. Named for the closed/open
  // split it sits beside, not for mark-to-market.
  unrealized: number;
  win_rate: number | null;
  closed_count: number;
  open_count: number;
  net_liquidation: number | null;
  yield_pct: number | null;
  // True when a trade's currency differs from the account's base currency
  // (or, combined, when accounts disagree). yield_pct is converted through a
  // live FX rate when one is available and null only when it isn't.
  currency_mismatch: boolean;
  base_currency?: string | null;
  // The single currency the account's premiums are denominated in, when known.
  premium_currency?: string | null;
  // Combined view only: the currency everything was converted into (null when
  // no conversion happened or a rate was missing).
  display_currency?: string | null;
  fx_rates?: FxRateInfo[];
  // Present only in the combined view. The derived P&L sums across accounts,
  // but the manual overlay (cashed out / withdrawal / note) belongs to one
  // account, so it is carried per account instead of merged.
  by_account?: (Income & { account_id: string; account_label: string })[];
}
