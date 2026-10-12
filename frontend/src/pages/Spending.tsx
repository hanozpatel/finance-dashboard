/**
 * Spending — where the money actually went, in depth.
 *
 * The period control sits once above everything it scopes, so every panel
 * re-renders against the same slice rather than each card carrying its own
 * filter.
 *
 * Each chart has a table-view twin. That is the documented relief for the three
 * light-mode palette hues that fall below 3:1 against the surface, and it is
 * also simply the better way to read exact numbers.
 */

import { Table2, BarChart3 } from 'lucide-react'
import { useState } from 'react'
import { Link } from 'react-router-dom'

import { RankedBars, StackedColumns, TrendArea } from '../components/charts'
import {
  Button, Card, CardHeader, DataTable, Delta, EmptyState, ErrorState, LegendKey, Loading,
  NumberInput, Segmented, SectionTitle, StatTile, money, moneyCompact,
} from '../components/ui'
import { useAsync } from '../hooks/useAsync'
import { api, type Budget, type CategorySpend, type MerchantSpend } from '../lib/api'
import { monthShort, pct, shortDate } from '../lib/format'

interface Baseline {
  median: number
  mean: number
  max: number
  min: number
  months: number
}

interface SpendingData {
  range: { start: string; end: string }
  summary: {
    spend: number
    income: number
    net: number
    days: number
    transactions: number
    daily_average: number
    savings_rate: number | null
    prev_spend: number
    prev_label: string
    spend_change_pct: number | null
  }
  by_category: CategorySpend[]
  by_subcategory: { category: string; subcategory: string; spend: number; n: number }[]
  by_merchant: MerchantSpend[]
  daily: { date: string; spend: number }[]
  category_trend: { months: string[]; categories: { category: string; values: number[] }[] }
  baselines: Record<string, Baseline>
}

const PERIODS = [
  { value: 1, label: 'This month' },
  { value: 3, label: '3 months' },
  { value: 6, label: '6 months' },
  { value: 12, label: '12 months' },
]

export default function Spending({ version }: { version: number }) {
  const [months, setMonths] = useState(1)
  const [categoryView, setCategoryView] = useState<'chart' | 'table'>('chart')
  const [trendView, setTrendView] = useState<'chart' | 'table'>('chart')
  const [drill, setDrill] = useState<string | null>(null)

  const { data, error, loading, reload, refreshing } = useAsync<SpendingData>(
    () => api.spending({ months }), [months, version],
  )
  const budgets = useAsync<Budget[]>(() => api.budgets(), [version])

  if (loading) return <Loading label="Crunching your spending" />
  if (error) return <ErrorState message={error} onRetry={reload} />
  if (!data) return null

  const { summary } = data
  const subcategories = drill
    ? data.by_subcategory.filter((s) => s.category === drill)
    : data.by_subcategory.slice(0, 14)
  const merchants = drill
    ? data.by_merchant.filter((m) => m.category === drill)
    : data.by_merchant

  return (
    <div className={refreshing ? 'opacity-70 transition-opacity' : undefined}>
      {/* One filter row, above everything it scopes. */}
      <div className="mb-4 flex flex-wrap items-center gap-3">
        <Segmented options={PERIODS} value={months} onChange={setMonths} />
        <span className="text-xs text-[var(--text-muted)]">
          {shortDate(data.range.start)} – {shortDate(data.range.end)} · {summary.days} days
        </span>
        {drill && (
          <Button size="sm" variant="ghost" onClick={() => setDrill(null)}>
            Clear “{drill}” filter ✕
          </Button>
        )}
      </div>

      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-5">
        <StatTile
          label="Total spent"
          value={money(summary.spend, false)}
          delta={summary.spend_change_pct}
          deltaLabel={`vs ${summary.prev_label}`}
          upIsGood={false}
        />
        <StatTile label="Daily average" value={money(summary.daily_average, false)} />
        <StatTile label="Transactions" value={summary.transactions.toLocaleString()} />
        <StatTile label="Income" value={money(summary.income, false)} />
        <StatTile
          label="Kept"
          value={money(summary.net, false)}
          sub={summary.savings_rate !== null ? `${pct(summary.savings_rate, 0)} savings rate` : undefined}
        />
      </div>

      <SectionTitle hint="Click a category to filter the merchant and subcategory panels below it.">
        By category
      </SectionTitle>
      <Card>
        <CardHeader
          title={drill ? `${drill} only` : 'Every category'}
          subtitle={`Compared with ${summary.prev_label}, and with your own running median`}
          action={
            <Segmented
              size="sm"
              value={categoryView}
              onChange={setCategoryView}
              options={[{ value: 'chart', label: 'Chart' }, { value: 'table', label: 'Table' }]}
            />
          }
        />
        {!data.by_category.length ? (
          <EmptyState title="No spending in this period." />
        ) : categoryView === 'chart' ? (
          <RankedBars
            items={data.by_category.map((c) => ({
              label: c.category,
              value: c.spend,
              sublabel: `${c.share}% · ${c.transactions} transactions`,
            }))}
            maxBars={14}
          />
        ) : (
          <DataTable
            columns={[
              {
                key: 'category',
                header: 'Category',
                render: (c) => (
                  <button
                    onClick={() => setDrill(c.category)}
                    className="font-medium text-[var(--text-primary)] hover:underline"
                  >
                    {c.category}
                  </button>
                ),
              },
              { key: 'spend', header: 'Spent', align: 'right', numeric: true,
                render: (c) => <span className="font-semibold">{money(c.spend)}</span> },
              { key: 'share', header: 'Share', align: 'right', numeric: true,
                render: (c) => <span className="text-[var(--text-secondary)]">{pct(c.share)}</span> },
              { key: 'n', header: 'Count', align: 'right', numeric: true,
                render: (c) => <span className="text-[var(--text-muted)]">{c.transactions}</span> },
              {
                key: 'change',
                header: 'vs prior',
                align: 'right',
                numeric: true,
                render: (c) =>
                  c.change_pct !== null
                    ? <Delta value={c.change_pct} upIsGood={false} />
                    : <span className="text-xs text-[var(--text-muted)]">new</span>,
              },
              {
                key: 'baseline',
                header: 'Typical month',
                align: 'right',
                numeric: true,
                render: (c) => {
                  const b = data.baselines[c.category]
                  if (!b) return <span className="text-xs text-[var(--text-muted)]">—</span>
                  return (
                    <span className="text-xs text-[var(--text-secondary)]">
                      {money(b.median, false)}
                      <span className="text-[var(--text-muted)]"> ({b.months}mo median)</span>
                    </span>
                  )
                },
              },
            ]}
            rows={data.by_category}
            rowKey={(c) => c.category}
            footer={
              <tr>
                <td className="pt-2 text-xs font-semibold text-[var(--text-secondary)]">Total</td>
                <td className="tnum pt-2 text-right font-semibold">{money(summary.spend)}</td>
                <td colSpan={4} />
              </tr>
            }
          />
        )}
        {categoryView === 'chart' && data.by_category.length > 0 && (
          <div className="mt-3 flex flex-wrap items-center gap-2">
            {data.by_category.slice(0, 14).map((c) => (
              <button
                key={c.category}
                onClick={() => setDrill(c.category)}
                className="rounded-md border px-2 py-1 text-xs text-[var(--text-secondary)] hover:bg-[var(--surface-2)]"
                style={{ borderColor: 'var(--border)' }}
              >
                {c.category}
              </button>
            ))}
          </div>
        )}
      </Card>

      <div className="mt-4 grid gap-4 lg:grid-cols-2">
        <Card>
          <CardHeader
            title="Category mix over six months"
            subtitle="Stacked to the monthly total; smaller categories are folded into Other"
            action={
              <Segmented
                size="sm"
                value={trendView}
                onChange={setTrendView}
                options={[
                  { value: 'chart', label: <BarChart3 size={12} /> },
                  { value: 'table', label: <Table2 size={12} /> },
                ]}
              />
            }
          />
          {trendView === 'chart' ? (
            <>
              <StackedColumns
                labels={data.category_trend.months.map(monthShort)}
                series={data.category_trend.categories.map((c) => ({
                  name: c.category,
                  values: c.values,
                }))}
                height={300}
                showLegend={false}
              />
              {/* Swatch keys outside the plot: identity is never colour-alone. */}
              <div className="mt-2">
                <LegendKey
                  items={data.category_trend.categories.map((c, i) => ({
                    label: c.category,
                    colorIndex: i,
                    value: moneyCompact(c.values.reduce((s, v) => s + v, 0)),
                  }))}
                />
              </div>
            </>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr>
                    <th className="border-b pb-2 text-left text-xs font-medium text-[var(--text-muted)]"
                        style={{ borderColor: 'var(--border)' }}>Category</th>
                    {data.category_trend.months.map((m) => (
                      <th key={m}
                          className="border-b pb-2 text-right text-xs font-medium text-[var(--text-muted)]"
                          style={{ borderColor: 'var(--border)' }}>
                        {monthShort(m)}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {data.category_trend.categories.map((c) => (
                    <tr key={c.category} className="border-b last:border-0"
                        style={{ borderColor: 'var(--border)' }}>
                      <td className="py-2 font-medium">{c.category}</td>
                      {c.values.map((v, i) => (
                        <td key={i} className="tnum py-2 text-right text-[var(--text-secondary)]">
                          {v ? moneyCompact(v) : '—'}
                        </td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </Card>

        <Card>
          <CardHeader
            title="Daily spending"
            subtitle="Every posted transaction in the period, by day"
          />
          {data.daily.length > 1 ? (
            <TrendArea
              labels={data.daily.map((d) => shortDate(d.date))}
              values={data.daily.map((d) => d.spend)}
              height={300}
              showEndLabel={false}
              colorIndex={1}
              valueLabel="Spent"
            />
          ) : (
            <EmptyState title="Not enough days in this period to chart." />
          )}
        </Card>
      </div>

      <div className="mt-4 grid gap-4 lg:grid-cols-2">
        <Card>
          <CardHeader
            title={drill ? `${drill} merchants` : 'Top merchants'}
            subtitle="Grouped across name variations — store numbers and order ids are stripped"
          />
          <DataTable
            dense
            columns={[
              {
                key: 'merchant',
                header: 'Merchant',
                render: (m) => (
                  <Link
                    to={`/transactions?merchant=${encodeURIComponent(m.merchant_key)}`}
                    className="font-medium text-[var(--text-primary)] hover:underline"
                  >
                    {m.merchant}
                  </Link>
                ),
              },
              { key: 'category', header: 'Category',
                render: (m) => <span className="text-xs text-[var(--text-muted)]">{m.category}</span> },
              { key: 'n', header: 'Times', align: 'right', numeric: true,
                render: (m) => <span className="text-[var(--text-secondary)]">{m.transactions}</span> },
              { key: 'avg', header: 'Average', align: 'right', numeric: true,
                render: (m) => <span className="text-[var(--text-secondary)]">{money(m.avg_amount)}</span> },
              { key: 'spend', header: 'Total', align: 'right', numeric: true,
                render: (m) => <span className="font-semibold">{money(m.spend)}</span> },
            ]}
            rows={merchants.slice(0, 20)}
            rowKey={(m) => m.merchant_key}
            empty={drill ? `No ${drill} merchants in this period.` : 'No merchants yet.'}
          />
        </Card>

        <Card>
          <CardHeader
            title={drill ? `${drill} breakdown` : 'Biggest subcategories'}
            subtitle="The level where substitutions become obvious — delivery against groceries, coffee against everything"
          />
          <DataTable
            dense
            columns={[
              {
                key: 'sub',
                header: 'Subcategory',
                render: (s) => (
                  <div>
                    <span className="font-medium text-[var(--text-primary)]">{s.subcategory}</span>
                    {!drill && (
                      <span className="ml-1.5 text-xs text-[var(--text-muted)]">{s.category}</span>
                    )}
                  </div>
                ),
              },
              { key: 'n', header: 'Count', align: 'right', numeric: true,
                render: (s) => <span className="text-[var(--text-muted)]">{s.n}</span> },
              { key: 'spend', header: 'Total', align: 'right', numeric: true,
                render: (s) => <span className="font-semibold">{money(s.spend)}</span> },
            ]}
            rows={subcategories}
            rowKey={(s) => `${s.category}-${s.subcategory}`}
            empty="No subcategories in this period."
          />
        </Card>
      </div>

      <SectionTitle hint="A limit here drives the budget meters on Overview and the pacing warnings under Find Savings.">
        Monthly budgets
      </SectionTitle>
      <Card>
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {data.by_category.slice(0, 9).map((c) => {
            const existing = budgets.data?.find((b) => b.category === c.category)
            const baseline = data.baselines[c.category]
            return (
              <div key={c.category}>
                <div className="mb-1 flex items-baseline justify-between gap-2">
                  <span className="text-xs font-medium text-[var(--text-secondary)]">
                    {c.category}
                  </span>
                  <span className="tnum text-xs text-[var(--text-muted)]">
                    {baseline ? `typical ${money(baseline.median, false)}` : ''}
                  </span>
                </div>
                <NumberInput
                  value={existing?.limit ?? 0}
                  prefix="$"
                  step={25}
                  min={0}
                  onChange={async (next) => {
                    await api.setBudget(c.category, next)
                    budgets.reload()
                  }}
                />
              </div>
            )
          })}
        </div>
        <p className="mt-3 text-xs text-[var(--text-muted)]">
          Set a limit to 0 to remove it. “Typical” is your own median month for that category over
          the last six complete months — a defensible starting point, since it is what you already
          spend rather than an arbitrary target.
        </p>
      </Card>
    </div>
  )
}
