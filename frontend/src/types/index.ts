// Mirrors the Pydantic response models in api/routes/dashboard_ui.py.
// Keep field names and optionality in lock-step with the backend — the
// client casts raw JSON to these shapes with no runtime validation.

// ---------------------------------------------------------------------------
// /api/dashboard/today-picks
// ---------------------------------------------------------------------------

export interface BankrollSnapshot {
  paper_balance: number;
  paper_initial: number;
  paper_return_pct: number | null;
  live_balance_aud: number | null;
}

export interface PickRecommendation {
  rec_id: number;
  side: "home" | "away";
  recommended_odds: number;
  edge: number | null;
  kelly_fraction: number;
  suggested_stake_aud: number | null;
  using_live_bankroll: boolean;
}

export interface PickMatch {
  match_id: number;
  home_team: string;
  away_team: string;
  venue: string | null;
  match_time: string | null;
  minutes_until: number | null;
  round_label: string | null;
  is_final: boolean;
  home_win_prob: number;
  away_win_prob: number;
  recommendation: PickRecommendation | null;
}

export interface TodayPicksResponse {
  generated_at: string;
  days_ahead: number;
  n_matches: number;
  next_match_minutes: number | null;
  bankroll: BankrollSnapshot;
  picks: PickMatch[];
}

// ---------------------------------------------------------------------------
// /api/dashboard/performance
// ---------------------------------------------------------------------------

export interface PerformanceSummary {
  total_bets: number;
  settled: number;
  pending: number;
  wins: number;
  losses: number;
  win_rate_pct: number | null;
  total_pl_units: number;
  roi_pct: number | null;
  brier_best: number | null;
}

export interface RecentMatch {
  match_id: number;
  home_team: string;
  away_team: string;
  match_time: string | null;
  round_label: string | null;
  predicted_side: "home" | "away";
  predicted_prob: number;
  actual_result: "home" | "away" | "draw" | null;
  correct: boolean | null;
}

export interface BankrollPoint {
  round_label: string;
  balance: number;
}

export interface ModelAccuracy {
  model_name: string;
  accuracy: number | null;
  brier: number | null;
  log_loss: number | null;
  trained_at: string | null;
}

export interface PerformanceResponse {
  summary: PerformanceSummary;
  recent_matches: RecentMatch[];
  bankroll_history: BankrollPoint[];
  model_comparison: ModelAccuracy[];
}

// ---------------------------------------------------------------------------
// /api/dashboard/odds-tracker
// ---------------------------------------------------------------------------

export interface OddsHistoryPoint {
  at: string;
  home_odds: number | null;
  away_odds: number | null;
  bookmaker: string;
}

export interface OddsTrackerMatch {
  match_id: number;
  home_team: string;
  away_team: string;
  match_time: string | null;
  round_label: string | null;
  tab_home_odds: number | null;
  tab_away_odds: number | null;
  tab_home_implied: number | null;
  tab_away_implied: number | null;
  model_home_prob: number | null;
  model_away_prob: number | null;
  home_edge: number | null;
  away_edge: number | null;
  history: OddsHistoryPoint[];
}

export interface OddsTrackerResponse {
  round_label: string | null;
  round_number: number | null;
  n_matches: number;
  matches: OddsTrackerMatch[];
}

// ---------------------------------------------------------------------------
// /api/dashboard/backtest-summary
// ---------------------------------------------------------------------------

export interface EnsembleWeights {
  logistic: number;
  xgboost: number;
  poisson: number;
  elo: number;
  bookmaker: number;
}

export interface BacktestSummaryResponse {
  available: boolean;
  source_date: string | null;
  pipeline_status: string | null;
  season_roi_pct: number | null;
  bankroll_current: number | null;
  bankroll_peak: number | null;
  drawdown: number | null;
  n_settled: number;
  n_pending: number;
  ensemble_weights: EnsembleWeights;
  raw_summary: Record<string, unknown> | null;
}

// ---------------------------------------------------------------------------
// /api/dashboard/system-status
// ---------------------------------------------------------------------------

export interface JobStatus {
  job_name: string;
  last_status: string | null;
  last_run_at: string | null;
  age_hours: number | null;
  retry_count: number | null;
}

export interface DbRowCounts {
  matches: number;
  predictions: number;
  recommendations: number;
  odds_snapshots: number;
  bet_outcomes: number;
  bankroll_logs: number;
}

export interface OddsApiUsage {
  monthly_limit: number;
  monthly_used_estimate: number;
  monthly_remaining_estimate: number;
  month: string;
  note: string;
}

export interface ReadinessCheckDto {
  name: string;
  status: "pass" | "warn" | "fail" | "unknown";
  detail: string;
}

export interface SystemStatusResponse {
  checked_at: string;
  node_role: string;
  phase: string;
  jobs: JobStatus[];
  db_rows: DbRowCounts;
  odds_api: OddsApiUsage;
  readiness_overall: "ready" | "marginal" | "not_ready" | "unknown";
  readiness_checks: ReadinessCheckDto[];
}

// ---------------------------------------------------------------------------
// Endpoint → response type map. Used by useApi<T>() for inference.
// ---------------------------------------------------------------------------

export interface DashboardEndpointMap {
  "/api/dashboard/today-picks": TodayPicksResponse;
  "/api/dashboard/performance": PerformanceResponse;
  "/api/dashboard/odds-tracker": OddsTrackerResponse;
  "/api/dashboard/backtest-summary": BacktestSummaryResponse;
  "/api/dashboard/system-status": SystemStatusResponse;
}

export type DashboardEndpoint = keyof DashboardEndpointMap;
