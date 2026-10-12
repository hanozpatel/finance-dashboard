/**
 * Overview — the state of things, in the order you would ask.
 *
 * Net worth is the hero (exactly one per view). Income and spending are plotted
 * as grouped columns rather than on one axis with a savings-rate line, because
 * a dollar axis and a percent axis on one plot invents a relationship that is
 * not in the data.
 */

import { ArrowRight } from 'lucide-react'
import { Link } from 'react-router-dom'

import { GroupedColumns, RankedBars, TrendArea } from '../components/charts'
import {
  Badge, Card, CardHeader, DataTable, EmptyState, ErrorState, Hero, Loading, Meter,
  SectionTitle, StatTile, money, moneyCompact,
} from '../components/ui'
import { useAsync } from '../hooks/useAsync'
import { api, type Account, type Budget, type CashFlowMonth, type CategorySpend, type NetWorth } from '../lib/api'
import { monthLabel, monthShort, pct, relativeDays } from '../lib/format'

interface OverviewData {
  net_worth: NetWorth
  net_worth_trend: { month: string; assets: number; liabilities: number; net_worth: number }[]
  cash_flow: CashFlowMonth[]
  this_month: {
    spend: number
    income: number
    net: number
    transactions: number
    daily_average: number
    savings_rate: number | null
    prev_spend: number
    prev_label: string
    spend_change_pct: number | null
  }
  top_categories: CategorySpend[]
  budgets: Budget[]
  accounts: Account[]
}

export default function Overview({ version }: { version: number }) {
  const { data, error, loading, reload, refreshing } = useAsync<OverviewData>(
    () => api.overview(12), [version],
  )

  if (loading) return <Loading label="Loading your finances" />
  if (error) return <ErrorState message={error} onRetry={reload} />
  if (!data) return null

  const trend = data.net_worth_trend
  // Month-over-month change in net worth, from the two most recent month-end
  // snapshots. With only one point there is no change to report.
  const netWorthDelta = trend.length >= 2
    ? ((trend[trend.length - 1].net_worth - trend[trend.length - 2].net_worth)
        / Math.abs(trend[trend.length - 2].net_worth || 1)) * 100
    : null

  const complete = data.cash_flow.filter((_, i) => i < data.cash_flow.length - 1)
  const medianRate = complete.length
    ? [...complete.map((m) => m.savings_rate).filter((r): r is number => r !== null)]
        .sort((a, b) => a - b)[Math.floor(complete.filter((m) => m.savings_rate !== null).length / 2)]
    : null

  const overBudget = data.budgets.filter((b) => !b.on_track)

  return (
    <div className={refreshing ? 'opacity-70 transition-opacity' : undefined}>
      <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_minmax(0,2fr)]">
        <Card className="flex flex-col justify-between">
          <Hero
            label="Net worth"
            value={money(data.net_worth.net_worth, false)}
            delta={netWorthDelta}
            deltaLabel="vs last month"
            footnote={`${money(data.net_worth.assets, false)} in assets less ${money(data.net_worth.liabilities, false)} owed`}
          />
          <div className="mt-4 grid grid-cols-3 gap-2 text-xs">
            <div>
              <div className="text-[var(--text-muted)]">Cash</div>
              <div className="tnum font-semibold">{moneyCompact(data.net_worth.cash)}</div>
            </div>
            <div>
              <div className="text-[var(--text-muted)]">Invested</div>
              <div className="tnum font-semibold">{moneyCompact(data.net_worth.invested)}</div>
            </div>
            <div>
              <div className="text-[var(--text-muted)]">Owed</div>
              <div className="tnum font-semibold">{moneyCompact(data.net_worth.liabilities)}</div>
            </div>
          </div>
        </Card>

        <Card>
          <CardHeader
            title="Net worth over time"
            subtitle="Month-end balances across every linked account"
          />
          {trend.length > 1 ? (
            <TrendArea
              labels={trend.map((t) => monthShort(t.month))}
              values={trend.map((t) => t.net_worth)}
              height={212}
              valueLabel="Net worth"
            />
          ) : (
            <EmptyState title="Not enough history yet">
              A trend appears once there are at least two month-end snapshots.
            </EmptyState>
          )}
        </Card>
      </div>

      <SectionTitle
        hint={`This calendar month so far, compared with ${data.this_month.prev_label}.`}
      >
        This month
      </SectionTitle>
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <StatTile
          label="Spent"
          value={money(data.this_month.spend, false)}
          delta={data.this_month.spend_change_pct}
          deltaLabel={`vs ${data.this_month.prev_label}`}
          upIsGood={false}
          sub={`${money(data.this_month.daily_average, false)}/day · ${data.this_month.transactions} transactions`}
        />
        <StatTile
          label="Income"
          value={money(data.this_month.income, false)}
        />
        <StatTile
          label="Net"
          value={money(data.this_month.net, false)}
          sub={data.this_month.net >= 0 ? 'Spending less than you earned' : 'Spending more than you earned'}
        />
        <StatTile
          label="Savings rate"
          value={data.this_month.savings_rate !== null ? pct(data.this_month.savings_rate, 0) : '—'}
          sub={medianRate !== null ? `${pct(medianRate, 0)} median over the last year` : undefined}
        />
      </div>

      <div className="mt-4 grid gap-4 lg:grid-cols-2">
        <Card>
          <CardHeader
            title="Income against spending"
            subtitle="Both in dollars, so they share one axis"
          />
          <GroupedColumns
            labels={data.cash_flow.map((m) => monthShort(m.month))}
            series={[
              { name: 'Income', values: data.cash_flow.map((m) => m.income), colorIndex: 0 },
              { name: 'Spending', values: data.cash_flow.map((m) => m.spend), colorIndex: 1 },
            ]}
            height={260}
          />
        </Card>

        <Card>
          <CardHeader
            title="Where this month went"
            subtitle="Top categories by spend"
            action={
              <Link
                to="/spending"
                className="inline-flex items-center gap-1 text-xs font-medium text-[var(--text-secondary)] hover:text-[var(--text-primary)]"
              >
                All categories <ArrowRight size={12} />
              </Link>
            }
          />
          {data.top_categories.length ? (
            <RankedBars
              items={data.top_categories.map((c) => ({
                label: c.category,
                value: c.spend,
                sublabel: `${c.share}% of spend · ${c.transactions} transactions`,
              }))}
              maxBars={6}
            />
          ) : (
            <EmptyState title="No spending recorded this month yet." />
          )}
        </Card>
      </div>

      <div className="mt-4 grid gap-4 lg:grid-cols-[minmax(0,3fr)_minmax(0,2fr)]">
        <Card>
          <CardHeader title="Accounts" subtitle="Balances as of the last sync" />
          <DataTable
            columns={[
              {
                key: 'name',
                header: 'Account',
                render: (a) => (
                  <div>
                    <div className="font-medium text-[var(--text-primary)]">{a.name}</div>
                    <div className="text-xs text-[var(--text-muted)]">
                      {a.institution}
                      {a.mask ? ` ···· ${a.mask}` : ''}
                    </div>
                  </div>
                ),
              },
              {
                key: 'type',
                header: 'Type',
                render: (a) => (
                  <span className="text-xs capitalize text-[var(--text-secondary)]">
                    {a.subtype?.replace(/_/g, ' ') ?? a.type}
                  </span>
                ),
              },
              {
                key: 'apy',
                header: 'APY',
                align: 'right',
                numeric: true,
                render: (a) => (
                  <span className="text-xs text-[var(--text-secondary)]">
                    {a.apy ? pct(a.apy, 2) : '—'}
                  </span>
                ),
              },
              {
                key: 'synced',
                header: 'Updated',
                align: 'right',
                render: (a) => (
                  <span className="text-xs text-[var(--text-muted)]">
                    {relativeDays(a.last_synced?.slice(0, 10))}
                  </span>
                ),
              },
              {
                key: 'balance',
                header: 'Balance',
                align: 'right',
                numeric: true,
                render: (a) => (
                  <span
                    className="font-semibold"
                    style={{ color: a.balance_current < 0 ? 'var(--danger-text)' : undefined }}
                  >
                    {money(a.balance_current)}
                  </span>
                ),
              },
            ]}
            rows={data.accounts}
            rowKey={(a) => a.id}
          />
        </Card>

        <Card>
          <CardHeader
            title="Budgets"
            subtitle={
              overBudget.length
                ? `${overBudget.length} pacing over`
                : 'All categories on pace'
            }
            action={
              overBudget.length ? <Badge tone="warning">{overBudget.length} over</Badge> : undefined
            }
          />
          {data.budgets.length ? (
            <div className="space-y-3">
              {data.budgets.map((b) => (
                <Meter
                  key={b.category}
                  label={b.category}
                  value={b.spent}
                  max={b.limit}
                  right={`${money(b.spent, false)} / ${money(b.limit, false)}`}
                  overflowLabel={
                    b.spent > b.limit
                      ? `${money(b.spent - b.limit, false)} over`
                      : `pacing to ${money(b.projected, false)}`
                  }
                  severity={b.spent > b.limit ? 'critical' : !b.on_track ? 'warning' : 'accent'}
                />
              ))}
            </div>
          ) : (
            <EmptyState title="No budgets set">
              Set a monthly limit on any category from the Spending tab.
            </EmptyState>
          )}
        </Card>
      </div>

      <p className="mt-4 text-xs text-[var(--text-muted)]">
        Transfers between your own accounts — paying the card from checking, moving money to
        savings — are excluded from spending, so the same dollar is never counted twice.
        Refunds are netted against the category they came from. Latest month shown is{' '}
        {data.cash_flow.length ? monthLabel(data.cash_flow[data.cash_flow.length - 1].month) : '—'}.
      </p>
    </div>
  )
}
