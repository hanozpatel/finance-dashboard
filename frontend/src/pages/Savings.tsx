/**
 * Find Savings — ranked, quantified places to cut.
 *
 * Three totals are shown rather than one, because a single number here would be
 * a lie by omission: several findings describe the same restaurant bill from
 * different angles, so their sum is a ceiling, not a target. The conservative
 * figure counts only the largest finding per category, and the easy figure
 * counts only what costs nothing to act on.
 *
 * Every card carries its *basis* — the assumption behind the estimate — so a
 * number you disagree with can be argued with instead of just distrusted.
 */

import { ChevronDown, ChevronUp, ExternalLink } from 'lucide-react'
import { useState } from 'react'
import { Link } from 'react-router-dom'

import { RankedBars } from '../components/charts'
import {
  Badge, Banner, Button, Card, CardHeader, DataTable, EmptyState, ErrorState, Hero,
  Loading, Meter, SectionTitle, Segmented, StatTile, money, moneyCompact,
} from '../components/ui'
import { useAsync } from '../hooks/useAsync'
import { api, errorMessage, type Insight, type InsightsResponse, type RecurringSeries } from '../lib/api'
import { mediumDate, pct, relativeDays } from '../lib/format'

const EFFORT_TONE = {
  easy: 'good',
  moderate: 'warning',
  hard: 'serious',
} as const

const EFFORT_LABEL = {
  easy: 'Easy',
  moderate: 'Some effort',
  hard: 'Hard',
} as const

export default function Savings({ version }: { version: number }) {
  const [expanded, setExpanded] = useState<Set<string>>(new Set())
  const [effortFilter, setEffortFilter] = useState<'all' | 'easy'>('all')
  const [subsVersion, setSubsVersion] = useState(0)
  const [note, setNote] = useState<string | null>(null)

  const insights = useAsync<InsightsResponse>(() => api.insights(), [version])
  const recurring = useAsync(() => api.recurring(), [version, subsVersion])

  if (insights.loading) return <Loading label="Looking for savings" />
  if (insights.error) return <ErrorState message={insights.error} onRetry={insights.reload} />
  if (!insights.data) return null

  const data = insights.data
  const shown = effortFilter === 'easy'
    ? data.insights.filter((i) => i.effort === 'easy')
    : data.insights

  async function setStatus(series: RecurringSeries, status: string) {
    try {
      await api.setSeriesStatus(series.id, status)
      setSubsVersion((v) => v + 1)
    } catch (e) {
      setNote(errorMessage(e))
    }
  }

  return (
    <div className={insights.refreshing ? 'opacity-70 transition-opacity' : undefined}>
      <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_minmax(0,2fr)]">
        <Card>
          <Hero
            label="Realistic annual saving"
            value={moneyCompact(data.conservative_annual)}
            footnote={`${money(data.conservative_monthly, false)} a month, counting only the largest opportunity in each category.`}
          />
        </Card>

        <div className="grid gap-3 sm:grid-cols-3">
          <StatTile
            label="Costs you nothing"
            value={money(data.easy_annual_total, false)}
            sub="Per year, from cancel-and-move items only"
            accent
          />
          <StatTile
            label="Conservative"
            value={money(data.conservative_annual, false)}
            sub="Largest finding per category, no double-counting"
          />
          <StatTile
            label="Ceiling"
            value={money(data.annual_total, false)}
            sub="If every item were acted on independently"
          />
        </div>
      </div>

      <div className="mt-3">
        <Banner tone="info" title="Why three numbers">{data.overlap_note}</Banner>
      </div>

      {note && (
        <div className="mt-3">
          <Banner tone="critical" onDismiss={() => setNote(null)}>{note}</Banner>
        </div>
      )}

      {data.insights.length > 0 && (
        <>
          <SectionTitle hint="Ranked by annual value. Effort is the honest cost of acting, not a nudge.">
            {data.count} opportunities
          </SectionTitle>

          <div className="mb-3 flex flex-wrap items-center gap-3">
            <Segmented
              value={effortFilter}
              onChange={setEffortFilter}
              options={[
                { value: 'all', label: `All ${data.count}` },
                { value: 'easy', label: `Easy only (${data.insights.filter((i) => i.effort === 'easy').length})` },
              ]}
            />
            <Link
              to="/house"
              className="ml-auto inline-flex items-center gap-1 text-xs font-medium text-[var(--text-secondary)] hover:text-[var(--text-primary)]"
            >
              See what this does to the house timeline <ExternalLink size={12} />
            </Link>
          </div>

          <Card className="mb-4">
            <CardHeader
              title="Opportunities by annual value"
              subtitle="The same findings, sized against each other"
            />
            <RankedBars
              items={shown.map((i) => ({
                label: i.title,
                value: i.annual_savings,
                sublabel: `${money(i.monthly_savings, false)}/mo · ${EFFORT_LABEL[i.effort]}`,
              }))}
              maxBars={14}
              colorIndex={2}
              labelWidth={280}
            />
          </Card>

          <div className="space-y-3">
            {shown.map((insight) => (
              <InsightCard
                key={insight.id}
                insight={insight}
                open={expanded.has(insight.id)}
                onToggle={() => {
                  const next = new Set(expanded)
                  if (next.has(insight.id)) next.delete(insight.id)
                  else next.add(insight.id)
                  setExpanded(next)
                }}
              />
            ))}
          </div>
        </>
      )}

      {!data.insights.length && (
        <Card className="mt-4">
          <EmptyState title="Nothing worth flagging yet">
            Opportunities need a few months of history to separate a real pattern from a one-off.
            Link an account or import a statement and check back.
          </EmptyState>
        </Card>
      )}

      <SectionTitle hint="Detected from rhythm, not from any label a bank supplied. Mark each one so the audit estimate reflects your actual decisions.">
        Recurring charges
      </SectionTitle>

      {recurring.data ? (
        <Card>
          <CardHeader
            title={`${recurring.data.active_count} active`}
            subtitle={`${money(recurring.data.monthly_total, false)}/mo · ${money(recurring.data.annual_total, false)}/yr committed`}
          />
          <DataTable
            dense
            columns={[
              {
                key: 'name',
                header: 'Charge',
                render: (s: RecurringSeries) => (
                  <div>
                    <div className="flex items-center gap-1.5">
                      <span className="font-medium text-[var(--text-primary)]">
                        {s.display_name}
                      </span>
                      {!s.is_active && <Badge tone="neutral" icon={false}>stopped</Badge>}
                      {s.price_increase && s.price_increase > 1.05 && (
                        <Badge tone="warning">
                          +{Math.round((s.price_increase - 1) * 100)}%
                        </Badge>
                      )}
                    </div>
                    <div className="text-xs text-[var(--text-muted)]">
                      {s.category ?? 'Uncategorized'} · {s.cadence} · seen {s.occurrences}×
                    </div>
                  </div>
                ),
              },
              {
                key: 'confidence',
                header: 'Confidence',
                align: 'right',
                render: (s: RecurringSeries) => (
                  <div className="w-20">
                    <Meter
                      value={s.confidence * 100}
                      max={100}
                      height={4}
                      severity={s.confidence > 0.8 ? 'good' : 'accent'}
                    />
                    <span className="tnum mt-0.5 block text-right text-xs text-[var(--text-muted)]">
                      {pct(s.confidence * 100, 0)}
                    </span>
                  </div>
                ),
              },
              {
                key: 'range',
                header: 'Amount',
                align: 'right',
                numeric: true,
                render: (s: RecurringSeries) => (
                  <div className="whitespace-nowrap">
                    <div className="font-semibold">{money(s.amount_median)}</div>
                    {s.amount_min !== s.amount_max && (
                      <div className="text-xs text-[var(--text-muted)]">
                        {money(s.amount_min, false)}–{money(s.amount_max, false)}
                      </div>
                    )}
                  </div>
                ),
              },
              {
                key: 'monthly',
                header: 'Per month',
                align: 'right',
                numeric: true,
                render: (s: RecurringSeries) => (
                  <span className="font-semibold">{money(s.monthly_cost)}</span>
                ),
              },
              {
                key: 'next',
                header: 'Next / last',
                align: 'right',
                render: (s: RecurringSeries) => (
                  <div className="whitespace-nowrap text-xs text-[var(--text-muted)]">
                    <div>{s.next_expected ? mediumDate(s.next_expected) : '—'}</div>
                    <div>last {relativeDays(s.last_date)}</div>
                  </div>
                ),
              },
              {
                key: 'status',
                header: 'Decision',
                align: 'right',
                render: (s: RecurringSeries) => (
                  <div className="flex justify-end gap-1">
                    {(['keep', 'review', 'cancelled'] as const).map((status) => (
                      <button
                        key={status}
                        onClick={() => setStatus(s, s.user_status === status ? 'none' : status)}
                        className="rounded border px-1.5 py-0.5 text-xs capitalize transition-colors"
                        style={{
                          borderColor: s.user_status === status
                            ? 'var(--series-1)' : 'var(--border)',
                          background: s.user_status === status
                            ? 'var(--accent-wash)' : 'transparent',
                          color: s.user_status === status
                            ? 'var(--text-primary)' : 'var(--text-muted)',
                        }}
                      >
                        {status === 'cancelled' ? 'cancel' : status}
                      </button>
                    ))}
                  </div>
                ),
              },
            ]}
            rows={recurring.data.series}
            rowKey={(s) => s.id}
            empty="No recurring charges detected yet — this needs at least three occurrences of a charge."
            footer={
              <tr>
                <td className="pt-2 text-xs font-semibold text-[var(--text-secondary)]">
                  Active total
                </td>
                <td colSpan={2} />
                <td className="tnum pt-2 text-right font-semibold">
                  {money(recurring.data.monthly_total)}
                </td>
                <td colSpan={2} />
              </tr>
            }
          />
          <p className="mt-3 text-xs text-[var(--text-muted)]">
            Confidence blends how regular the interval is, how stable the amount is, and how many
            times the charge has been seen. A usage-based bill like electricity is correctly
            detected as recurring but scores lower than a flat subscription, because the amount
            moves.
          </p>
        </Card>
      ) : (
        <Card><Loading label="Detecting recurring charges" /></Card>
      )}
    </div>
  )
}

function InsightCard({
  insight, open, onToggle,
}: { insight: Insight; open: boolean; onToggle: () => void }) {
  return (
    <Card>
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <h3 className="text-sm font-semibold text-[var(--text-primary)]">{insight.title}</h3>
            <Badge tone={EFFORT_TONE[insight.effort]}>{EFFORT_LABEL[insight.effort]}</Badge>
            <Badge tone="neutral" icon={false}>{insight.category}</Badge>
          </div>
          <p className="mt-1 text-sm text-[var(--text-secondary)]">{insight.summary}</p>
        </div>

        <div className="shrink-0 text-right">
          <div className="tnum text-xl font-semibold text-[var(--text-primary)]">
            {money(insight.monthly_savings, false)}
            <span className="text-xs font-normal text-[var(--text-muted)]">/mo</span>
          </div>
          <div className="tnum text-xs text-[var(--text-muted)]">
            {money(insight.annual_savings, false)}/yr
          </div>
        </div>
      </div>

      <button
        onClick={onToggle}
        className="mt-2 inline-flex items-center gap-1 text-xs font-medium text-[var(--text-secondary)] hover:text-[var(--text-primary)]"
        aria-expanded={open}
      >
        {open ? <ChevronUp size={13} /> : <ChevronDown size={13} />}
        {open ? 'Hide detail' : 'Why, and how it was estimated'}
      </button>

      {open && (
        <div className="mt-3 border-t pt-3" style={{ borderColor: 'var(--border)' }}>
          <p className="text-sm leading-relaxed text-[var(--text-secondary)]">{insight.detail}</p>

          <div className="mt-3 rounded-lg p-2.5 text-xs" style={{ background: 'var(--surface-2)' }}>
            <span className="font-semibold text-[var(--text-secondary)]">How this was estimated: </span>
            <span className="text-[var(--text-muted)]">{insight.basis}</span>
          </div>

          {insight.evidence.length > 0 && (
            <div className="mt-3">
              <div className="mb-1.5 text-xs font-semibold text-[var(--text-secondary)]">
                The numbers behind it
              </div>
              <DataTable
                dense
                columns={[
                  { key: 'label', header: 'Item',
                    render: (e: Insight['evidence'][number]) => (
                      <span className="text-[var(--text-secondary)]">{e.label}</span>) },
                  { key: 'count', header: 'Count', align: 'right', numeric: true,
                    render: (e) => (
                      <span className="text-[var(--text-muted)]">{e.count ?? '—'}</span>) },
                  { key: 'note', header: '', align: 'right',
                    render: (e) => (
                      <span className="text-xs text-[var(--text-muted)]">{e.note ?? ''}</span>) },
                  { key: 'amount', header: 'Amount', align: 'right', numeric: true,
                    render: (e) => <span className="font-semibold">{money(e.amount)}</span> },
                ]}
                rows={insight.evidence}
                rowKey={(e, i) => `${e.label}-${i}`}
              />
            </div>
          )}

          <div className="mt-3">
            <Link to={`/transactions?category=${encodeURIComponent(insight.category)}`}>
              <Button size="sm" variant="secondary">See the transactions</Button>
            </Link>
          </div>
        </div>
      )}
    </Card>
  )
}
