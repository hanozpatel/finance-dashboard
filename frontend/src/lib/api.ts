/** Typed client for the backend. One place that knows about URLs. */

import axios from 'axios'

import { STATIC_DEMO, demoAdapter } from './demo'

export const http = axios.create({
  baseURL: import.meta.env.VITE_API_BASE_URL || '',
  timeout: 120_000, // a first Plaid sync pulls years of history
  // The GitHub Pages preview has no server: every request is answered from a
  // snapshot of the demo data instead. Nothing else in the app knows.
  ...(STATIC_DEMO ? { adapter: demoAdapter } : {}),
})

/** Turn any axios failure into the message the API actually sent. */
export function errorMessage(e: unknown): string {
  if (axios.isAxiosError(e)) {
    const detail = e.response?.data?.detail
    if (typeof detail === 'string') return detail
    if (Array.isArray(detail) && detail.length) {
      // FastAPI validation errors arrive as a list of {loc, msg}.
      return detail
        .map((d: { loc?: (string | number)[]; msg?: string }) =>
          `${(d.loc ?? []).slice(1).join('.') || 'input'}: ${d.msg ?? 'invalid'}`)
        .join('; ')
    }
    if (e.code === 'ECONNABORTED') return 'The request timed out.'
    if (!e.response) return 'Could not reach the backend. Is it running on port 8001?'
    return `${e.response.status} ${e.response.statusText}`
  }
  return e instanceof Error ? e.message : String(e)
}

// --- types -----------------------------------------------------------------

export interface Account {
  id: number
  provider: string
  institution: string
  name: string
  mask: string | null
  type: 'depository' | 'credit' | 'investment'
  subtype: string | null
  balance_current: number
  balance_available: number | null
  credit_limit: number | null
  apy: number | null
  account_number: string | null
  notes: string | null
  is_active: number
  last_synced: string | null
  connection_status?: string | null
  connection_error?: string | null
  transaction_count?: number
  latest_transaction?: string | null
}

export interface NetWorth {
  net_worth: number
  assets: number
  liabilities: number
  cash: number
  invested: number
  by_type: Record<string, number>
}

export interface Transaction {
  id: number
  account_id: number
  date: string
  amount: number
  description: string
  merchant: string | null
  merchant_key: string | null
  category: string
  subcategory: string | null
  is_transfer: number
  pending: number
  excluded: number
  notes: string | null
  recurring_id: number | null
  recurring_name: string | null
  recurring_cadence: string | null
  account_name: string
  institution: string
  account_type: string
  mask: string | null
}

export interface CategorySpend {
  category: string
  spend: number
  transactions: number
  share: number
  prev_spend: number | null
  change: number | null
  change_pct: number | null
}

export interface MerchantSpend {
  merchant_key: string
  merchant: string
  category: string
  spend: number
  transactions: number
  avg_amount: number
  last_date: string
}

export interface CashFlowMonth {
  month: string
  income: number
  spend: number
  net: number
  savings_rate: number | null
}

export interface RecurringSeries {
  id: number
  merchant_key: string
  display_name: string
  category: string | null
  cadence: string
  interval_days: number
  amount_median: number
  amount_min: number
  amount_max: number
  monthly_cost: number
  occurrences: number
  first_date: string
  last_date: string
  next_expected: string | null
  confidence: number
  is_active: number
  user_status: 'none' | 'keep' | 'review' | 'cancelled'
  price_increase: number | null
}

export interface Insight {
  id: string
  kind: string
  title: string
  summary: string
  detail: string
  monthly_savings: number
  annual_savings: number
  effort: 'easy' | 'moderate' | 'hard'
  category: string
  basis: string
  evidence: { label: string; amount: number; count?: number; note?: string }[]
}

export interface InsightsResponse {
  insights: Insight[]
  monthly_total: number
  annual_total: number
  conservative_monthly: number
  conservative_annual: number
  easy_monthly_total: number
  easy_annual_total: number
  overlap_note: string
  count: number
}

export interface CategoryRuleRow {
  id: number
  priority: number
  match_type: string
  pattern: string
  category: string
  subcategory: string | null
  is_transfer: number
  created_at: string
}

export interface BudgetRow {
  category: string
  budget: number | null
  spent: number
  projected: number | null
  typical: number | null
  state: number | null
  comparable: boolean
  not_comparable_reason: string | null
  net_credit: boolean
  vs_state_pct: number | null
  vs_budget_pct: number | null
  over_budget: boolean
  history: { month: string; spent: number }[]
}

export interface BudgetSettings {
  state: string
  state_name: string
  household_size: number
  state_chosen: boolean
}

export interface BudgetOverview {
  month: string
  is_current: boolean
  is_future: boolean
  elapsed_days: number
  days_in_month: number
  months: string[]
  settings: BudgetSettings
  source: {
    name: string
    url: string
    year: number
    lines: Record<string, { line: number; description: string }[]>
  }
  categories: BudgetRow[]
  totals: {
    spent: number
    projected: number | null
    state: number
    budget: number
    budgeted_categories: number
  }
}

export interface Budget {
  category: string
  limit: number
  spent: number
  remaining: number
  used_pct: number | null
  projected: number
  on_track: boolean
}

export interface HouseGoal {
  target_price: number
  down_payment_pct: number
  saved_amount: number
  monthly_contribution: number
  savings_apy: number
  interest_rate: number
  loan_term_years: number
  property_tax_rate: number
  insurance_annual: number
  hoa_monthly: number
  pmi_rate: number
  closing_cost_pct: number
  gross_annual_income: number
  monthly_debts: number
  credit_score: number
  current_rent: number
  home_appreciation: number
  investment_return: number
  rent_inflation: number
  marginal_tax_rate: number
  funding_account_ids: number[]
  saved_from_accounts: boolean
  state: string | null
  loan_type: 'conventional' | 'fha' | 'va' | 'jumbo'
  conforming_limit: number
  va_first_use: number
}

export interface StateInfo {
  code: string
  name: string
  property_tax_rate: number
  median_home_price: number
  insurance_annual: number
  closing_cost_pct: number
  note: string | null
}

export interface LoanOption {
  loan_type: 'conventional' | 'fha' | 'va' | 'jumbo'
  label: string
  selected: boolean
  monthly: number
  principal_interest: number
  mortgage_insurance: number
  mi_rule: string
  loan_amount: number
  financed_fee: number
  fee_label: string | null
  cash_needed: number
  lifetime_interest: number
  lifetime_mi: number
  lifetime_cost: number
  back_end_dti: number
  verdict: string
  warnings: string[]
}

export interface PaymentBreakdown {
  home_price: number
  down_payment: number
  loan_amount: number
  ltv: number
  principal_interest: number
  property_tax: number
  insurance: number
  hoa: number
  pmi: number
  total_monthly: number
  piti: number
  base_loan: number
  financed_fee: number
  fee_label: string | null
  loan_type: string
  mi_rule: string
  mi_annual_pct: number
  warnings: string[]
}

export interface HousePlan {
  goal: HouseGoal
  payment: PaymentBreakdown
  dti: {
    gross_monthly: number
    front_end: number
    back_end: number
    passes_conventional: boolean
    passes_qm: boolean
    verdict: 'comfortable' | 'qualifies' | 'stretched' | 'over_limit' | 'unknown'
    max_housing_at_36: number
    headroom: number
  }
  cash_needed: { down_payment: number; closing_costs: number; total: number }
  projection: {
    months: number | null
    years: number | null
    reachable: boolean
    target_date: string | null
    shortfall: number
    projected_interest: number
  }
  affordability: {
    max_price: number
    price_by_income: number
    price_by_cash: number
    limited_by: 'cash' | 'income'
    monthly_budget: number
    down_payment: number
  }
  schedule_summary: {
    months: number
    payoff_years: number
    total_interest: number
    total_pmi: number
    total_paid: number
    pmi_ends_month: number | null
    pmi_request_month: number | null
    monthly_pi: number
  }
  equity_by_year: {
    year: number
    balance: number
    home_value: number
    equity: number
    cumulative_interest: number
  }[]
  rent_vs_buy: {
    horizon_years: number
    yearly: {
      year: number
      home_value: number
      loan_balance: number
      buyer_equity: number
      buyer_net_worth: number
      renter_net_worth: number
      advantage: number
      annual_tax_benefit: number
      monthly_rent: number
      buyer_monthly_cost: number
    }[]
    buyer_net_worth: number
    renter_net_worth: number
    advantage: number
    verdict: 'buy' | 'rent'
    breakeven_year: number | null
    total_spent_buying: number
    total_spent_renting: number
  }
  scenarios: {
    label: string
    down_payment_pct: number
    interest_rate: number
    loan_term_years: number
    monthly: number
    principal_interest: number
    pmi: number
    cash_needed: number
    months_to_save: number | null
    ready_date: string | null
    total_interest: number
    total_pmi: number
    back_end_dti: number
    verdict: string
  }[]
  readiness: {
    checks: {
      label: string
      status: 'done' | 'on_track' | 'todo' | 'warn' | 'blocked'
      detail: string
      progress: number
    }[]
    ready: boolean
    blocking_count: number
  }
  savings_impact: {
    available: boolean
    base_months?: number | null
    base_date?: string | null
    options?: {
      label: string
      extra_monthly: number
      months: number | null
      target_date: string | null
      months_saved: number | null
      note: string
    }[]
  }
  monthly_vs_rent: number
  loan_comparison: LoanOption[]
  state: StateInfo | null
  states: StateInfo[]
  income_context: {
    available: boolean
    median_monthly_income?: number
    median_monthly_net?: number
    median_savings_rate?: number
    months?: number
  }
}

export interface Holding {
  id: number
  symbol: string | null
  name: string
  security_type: string | null
  quantity: number
  price: number
  value: number
  cost_basis: number | null
  as_of: string
  account_name: string
  institution: string
  weight: number
  gain: number | null
  gain_pct: number | null
}

export type PlaidLinkKind = 'bank' | 'investments'

export interface ProviderStatus {
  plaid: {
    label: string
    purpose: string
    configured: boolean
    problem: string | null
    environment: string
    // An Item's products are fixed when it is created, so the two kinds are
    // separate links rather than one link with a wider scope.
    kinds: { kind: PlaidLinkKind; label: string; purpose: string; products: string[] }[]
  }
  snaptrade: {
    label: string
    purpose: string
    configured: boolean
    problem: string | null
    mode: 'personal' | 'commercial' | null
    registered: boolean
  }
  csv: { label: string; purpose: string; configured: boolean; problem: string | null }
  encryption: { key_from_environment: boolean; warning: string | null }
}

export interface ReviewSuggestion {
  category: string
  subcategory: string | null
  reason: string
  confidence: 'high' | 'medium' | 'low'
}

export interface ReviewQuestion {
  merchant_key: string
  merchant: string
  sample_description: string
  count: number
  total: number
  accounts: string[]
  first_date: string
  last_date: string
  transaction_ids: number[]
  examples: { id: number; date: string; amount: number; description: string; account: string }[]
  suggestions: ReviewSuggestion[]
}

export interface ReviewStats {
  total: number
  uncategorized: number
  questions: number
  amount: number
  coverage: number
}

export interface Connection {
  id: number
  provider: string
  institution: string | null
  provider_ref: string | null
  status: string
  error: string | null
  last_synced: string | null
  created_at: string
  account_count: number
}

// --- endpoints -------------------------------------------------------------

export const api = {
  health: () => http.get('/api/health').then((r) => r.data),

  accounts: () =>
    http.get<{ accounts: Account[]; net_worth: NetWorth }>('/api/accounts').then((r) => r.data),
  createAccount: (body: Record<string, unknown>) =>
    http.post<Account>('/api/accounts', body).then((r) => r.data),
  createTransaction: (body: Record<string, unknown>) =>
    http.post<{ inserted: number; balance: number; balance_updated: boolean }>(
      '/api/transactions', body).then((r) => r.data),
  updateAccount: (id: number, body: Record<string, unknown>) =>
    http.patch<Account>(`/api/accounts/${id}`, body).then((r) => r.data),
  deleteAccount: (id: number) => http.delete(`/api/accounts/${id}`).then((r) => r.data),

  overview: (months = 12) =>
    http.get(`/api/analytics/overview?months=${months}`).then((r) => r.data),
  spending: (params: { start?: string; end?: string; months?: number }) =>
    http.get('/api/analytics/spending', { params }).then((r) => r.data),
  cashFlow: (months = 12) =>
    http.get<{ cash_flow: CashFlowMonth[] }>(`/api/analytics/cash-flow?months=${months}`)
      .then((r) => r.data.cash_flow),
  merchants: (params: { start?: string; end?: string; months?: number; limit?: number; category?: string }) =>
    http.get<{ merchants: MerchantSpend[] }>('/api/analytics/by-merchant', { params })
      .then((r) => r.data.merchants),
  netWorthTrend: (months = 12) =>
    http.get(`/api/accounts/net-worth/trend?months=${months}`).then((r) => r.data.trend),

  transactions: (params: Record<string, unknown>) =>
    http.get<{
      transactions: Transaction[]
      total_count: number
      outflow: number
      inflow: number
      net: number
      has_more: boolean
    }>('/api/transactions', { params }).then((r) => r.data),
  updateTransaction: (id: number, body: Record<string, unknown>) =>
    http.patch(`/api/transactions/${id}`, body).then((r) => r.data),
  bulkCategorize: (body: {
    transaction_ids: number[]
    category: string
    subcategory?: string | null
    create_rule?: boolean
  }) => http.post('/api/transactions/bulk-categorize', body).then((r) => r.data),
  reviewQueue: () =>
    http.get<{ questions: ReviewQuestion[]; remaining: number; transactions: number; total_amount: number }>(
      '/api/transactions/review').then((r) => r.data),
  reviewStats: () => http.get<ReviewStats>('/api/transactions/review/stats').then((r) => r.data),
  reviewAnswer: (body: {
    merchant_key: string
    category: string
    subcategory: string | null
    create_rule: boolean
    transaction_ids?: number[]
  }) => http.post<{
    updated: number
    rule_created: string | null
    rule_skipped_reason: string | null
    remaining: number
  }>('/api/transactions/review/answer', body).then((r) => r.data),

  categories: () =>
    http.get<{ categories: string[]; subcategories: Record<string, string[]> }>(
      '/api/transactions/categories').then((r) => r.data),

  rules: () =>
    http.get<{ rules: CategoryRuleRow[] }>('/api/rules').then((r) => r.data.rules),
  createRule: (body: Record<string, unknown>) => http.post('/api/rules', body).then((r) => r.data),
  deleteRule: (id: number) => http.delete(`/api/rules/${id}`).then((r) => r.data),

  budgetOverview: (month?: string) =>
    http.get<BudgetOverview>('/api/budget/overview', { params: month ? { month } : {} })
      .then((r) => r.data),
  budgetSettings: () =>
    http.get<BudgetSettings & { areas: { code: string; name: string }[] }>('/api/budget/settings')
      .then((r) => r.data),
  saveBudgetSettings: (body: { state?: string; household_size?: number }) =>
    http.put<BudgetSettings>('/api/budget/settings', body).then((r) => r.data),
  fillBudgetsFromState: () =>
    http.post<{ filled: { category: string; monthly_limit: number }[]; skipped: string[] }>(
      '/api/budget/fill-from-state').then((r) => r.data),
  budgets: () => http.get<{ budgets: Budget[] }>('/api/budgets').then((r) => r.data.budgets),
  setBudget: (category: string, monthly_limit: number) =>
    http.put('/api/budgets', { category, monthly_limit }).then((r) => r.data),

  recurring: () =>
    http.get<{
      series: RecurringSeries[]
      monthly_total: number
      annual_total: number
      active_count: number
    }>('/api/recurring').then((r) => r.data),
  setSeriesStatus: (id: number, user_status: string) =>
    http.patch(`/api/recurring/${id}?user_status=${user_status}`).then((r) => r.data),
  seriesTransactions: (id: number) =>
    http.get<{ transactions: Transaction[] }>(`/api/recurring/${id}/transactions`)
      .then((r) => r.data.transactions),

  insights: () => http.get<InsightsResponse>('/api/insights').then((r) => r.data),

  housePlan: (params: { horizon_years?: number; extra_monthly?: number } = {}) =>
    http.get<HousePlan>('/api/goals/house', { params }).then((r) => r.data),
  updateHouseGoal: (body: Record<string, unknown>, applyStateDefaults = false) =>
    http.put<HousePlan>(
      `/api/goals/house?apply_state_defaults=${applyStateDefaults}`, body,
    ).then((r) => r.data),
  states: () =>
    http.get<{ states: StateInfo[]; note: string }>('/api/goals/states')
      .then((r) => r.data),
  mortgageQuote: (body: Record<string, unknown>, schedule = false) =>
    http.post(`/api/goals/mortgage?schedule=${schedule}`, body).then((r) => r.data),

  investments: () => http.get('/api/investments').then((r) => r.data),

  connections: () =>
    http.get<{ connections: Connection[]; providers: ProviderStatus }>('/api/connections')
      .then((r) => r.data),
  providers: () => http.get<ProviderStatus>('/api/connections/providers').then((r) => r.data),
  plaidLinkToken: (kind: PlaidLinkKind) =>
    http.post<{ link_token: string }>(`/api/connections/plaid/link-token?kind=${kind}`)
      .then((r) => r.data.link_token),
  connectPlaid: (body: Record<string, unknown>) =>
    http.post('/api/connections/plaid', body).then((r) => r.data),
  // No broker: SnapTrade's own picker, so any supported brokerage works.
  snaptradePortal: (broker?: string) =>
    http.post<{ url: string }>('/api/connections/snaptrade/portal', null,
      { params: broker ? { broker } : {} }).then((r) => r.data.url),
  snaptradeImport: () =>
    http.post<{ found: number; accounts: number; holdings: number }>(
      '/api/connections/snaptrade/import').then((r) => r.data),
  syncAll: () => http.post('/api/connections/sync').then((r) => r.data),
  syncOne: (id: number) => http.post(`/api/connections/${id}/sync`).then((r) => r.data),
  disconnect: (id: number, deleteAccounts = false) =>
    http.delete(`/api/connections/${id}?delete_accounts=${deleteAccounts}`).then((r) => r.data),

  importPreview: (file: File) => {
    const form = new FormData()
    form.append('file', file)
    return http.post('/api/imports/preview', form).then((r) => r.data)
  },
  importCommit: (accountId: number, uploadToken: string, mapping: Record<string, unknown>) => {
    const form = new FormData()
    form.append('account_id', String(accountId))
    form.append('upload_token', uploadToken)
    form.append('mapping_json', JSON.stringify(mapping))
    return http.post('/api/imports/commit', form).then((r) => r.data)
  },
  importPresets: () => http.get('/api/imports/presets').then((r) => r.data),

  seed: () => http.post('/api/seed?confirm=true').then((r) => r.data),
  clearDemo: () => http.post('/api/demo/clear?confirm=true').then((r) => r.data),
}
