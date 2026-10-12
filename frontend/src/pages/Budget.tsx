/**
 * Budget — each month, each category: what you planned, what you spent, and
 * what a household your size in your state spends.
 *
 * Three numbers per category, and the page is only useful if they stay apart:
 * the budget is yours to edit, the spend comes from the ledger, and the state
 * figure is an outside reference from BEA — a yardstick for whether a budget is
 * reasonable, never a target the app pushes you toward.
 *
 * The current month is still running, so it is judged on a *projection*: spend
 * so far plus your typical rate for the days left. Comparing day-12 spending
 * against a full month's average would make every category look comfortably
 * under until the 30th; straight-line pace overshoots on one big early purchase.
 */

import { ChevronLeft, ChevronRight, Info, MapPin, Sparkles, TriangleAlert } from 'lucide-react'
import { useEffect, useMemo, useState } from 'react'

import {
  Badge, Banner, Button, Card, CardHeader, ErrorState, Loading, SectionTitle, Select, StatTile,
  money, moneyCompact,
} from '../components/ui'
import { useAsync } from '../hooks/useAsync'
import { api, errorMessage, type BudgetOverview, type BudgetRow } from '../lib/api'
import { monthLabel, monthShort, signedPct } from '../lib/format'

function currentMonth(): string {
  const d = new Date()
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}`
}

function shiftMonth(month: string, by: number): string {
  const [y, m] = month.split('-').map(Number)
  const d = new Date(y, m - 1 + by, 1)
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}`
}

/** Diverging bin for spend relative to the state figure. Validated scale. */
function tint(ratio: number | null): string | null {
  if (ratio === null || !Number.isFinite(ratio)) return null
  if (ratio < 0.6) return 'var(--div-neg-2)'
  if (ratio < 0.9) return 'var(--div-neg-1)'
  if (ratio <= 1.1) return 'var(--div-mid)'
  if (ratio <= 1.5) return 'var(--div-pos-1)'
  return 'var(--div-pos-2)'
}

const LEGEND: { color: string; label: string }[] = [
  { color: 'var(--div-neg-2)', label: 'Under 60%' },
  { color: 'var(--div-neg-1)', label: '60–90%' },
  { color: 'var(--div-mid)', label: 'About average' },
  { color: 'var(--div-pos-1)', label: '110–150%' },
  { color: 'var(--div-pos-2)', label: 'Over 150%' },
]

export default function Budget({ version }: { version: number }) {
  const [month, setMonth] = useState(currentMonth())
  const [localVersion, setLocalVersion] = useState(0)
  const [note, setNote] = useState<{ tone: 'good' | 'critical'; text: string } | null>(null)

  const overview = useAsync(() => api.budgetOverview(month), [month, version, localVersion])
  const settings = useAsync(() => api.budgetSettings(), [version, localVersion])

  const refresh = () => setLocalVersion((v) => v + 1)

  async function saveSettings(body: { state?: string; household_size?: number }) {
    try {
      await api.saveBudgetSettings(body)
      refresh()
    } catch (e) {
      setNote({ tone: 'critical', text: errorMessage(e) })
    }
  }

  async function fillFromState() {
    try {
      const result = await api.fillBudgetsFromState()
      setNote({
        tone: 'good',
        text: result.filled.length
          ? `Set ${result.filled.length} budget${result.filled.length === 1 ? '' : 's'} to the `
            + `state average. Budgets you had already set were left alone.`
          : 'Every comparable category already has a budget — nothing was changed.',
      })
      refresh()
    } catch (e) {
      setNote({ tone: 'critical', text: errorMessage(e) })
    }
  }

  if (overview.loading && !overview.data) return <Loading label="Loading budget" />
  if (overview.error) return <ErrorState message={overview.error} onRetry={overview.reload} />
  const data = overview.data
  if (!data) return null

  const now = currentMonth()
  const s = data.settings
  const household = s.household_size === 1 ? 'one person' : `${s.household_size} people`

  return (
    <div>
      {note && (
        <div className="mb-4">
          <Banner tone={note.tone} onDismiss={() => setNote(null)}>{note.text}</Banner>
        </div>
      )}

      {/* Every control the page responds to, in one row above what it scopes. */}
      <Card className="mb-4">
        <div className="flex flex-wrap items-end gap-3">
          <div>
            <div className="mb-1 text-xs text-[var(--text-muted)]">Month</div>
            <div className="flex items-center gap-1">
              <Button size="sm" variant="ghost" onClick={() => setMonth(shiftMonth(month, -1))}>
                <ChevronLeft size={14} />
                <span className="sr-only">Previous month</span>
              </Button>
              <span className="min-w-[6.5rem] text-center text-sm font-semibold tabular-nums text-[var(--text-primary)]">
                {monthLabel(month)}
              </span>
              <Button
                size="sm"
                variant="ghost"
                disabled={month >= now}
                onClick={() => setMonth(shiftMonth(month, 1))}
              >
                <ChevronRight size={14} />
                <span className="sr-only">Next month</span>
              </Button>
            </div>
          </div>

          <div className="min-w-[12rem] flex-1 sm:flex-none">
            <div className="mb-1 flex items-center gap-1 text-xs text-[var(--text-muted)]">
              <MapPin size={11} /> State of residence
            </div>
            <Select
              value={s.state}
              onChange={(code) => saveSettings({ state: code })}
              options={(settings.data?.areas ?? []).map((a) => ({ value: a.code, label: a.name }))}
            />
          </div>

          <div className="w-36">
            <div className="mb-1 text-xs text-[var(--text-muted)]">Household size</div>
            <Select
              value={String(s.household_size)}
              onChange={(n) => saveSettings({ household_size: Number(n) })}
              options={Array.from({ length: 10 }, (_, i) => ({
                value: String(i + 1),
                label: i === 0 ? '1 person' : `${i + 1} people`,
              }))}
            />
          </div>

          <div className="ml-auto">
            <Button onClick={fillFromState}>
              <Sparkles size={14} />
              Fill empty budgets with state averages
            </Button>
          </div>
        </div>
      </Card>

      {!s.state_chosen && (
        <div className="mb-4">
          <Banner tone="info" title="Comparing against the national average">
            Choose your state above for a fairer yardstick — housing alone varies by more than
            2× between states.
          </Banner>
        </div>
      )}

      <div className="grid gap-4 sm:grid-cols-3">
        <StatTile
          label={data.is_current ? 'Projected for this month' : 'Spent this month'}
          value={money(data.is_current ? data.totals.projected : data.totals.spent, false)}
          sub={data.is_current
            ? `${money(data.totals.spent, false)} so far · day ${data.elapsed_days} of ${data.days_in_month}`
            : 'Comparable categories'}
          accent
        />
        <StatTile
          label={`${s.state_name} average`}
          value={money(data.totals.state, false)}
          sub={`A household of ${household}, per month`}
        />
        <StatTile
          label="Your budgets"
          value={data.totals.budgeted_categories ? money(data.totals.budget, false) : 'None set'}
          sub={data.totals.budgeted_categories
            ? `${data.totals.budgeted_categories} categor${data.totals.budgeted_categories === 1 ? 'y' : 'ies'}`
            : 'Set one per category below'}
        />
      </div>

      <SectionTitle hint={data.is_current
        ? 'The running month is judged on a projection: what you have spent so far, plus your typical spending for the days left.'
        : undefined}>
        {monthLabel(month)}, by category
      </SectionTitle>
      <MonthTable data={data} onSaved={refresh} onError={(t) => setNote({ tone: 'critical', text: t })} />

      <SectionTitle hint="Each cell is one month's spending, tinted by how it compares with the state average. Click a month to open it above.">
        The last 12 months
      </SectionTitle>
      <HistoryGrid data={data} selected={month} onSelect={setMonth} />

      <Methodology data={data} />
    </div>
  )
}

// ---------------------------------------------------------------------------
// The month table — the primary view, and the table-twin of every chart here
// ---------------------------------------------------------------------------

function MonthTable({
  data, onSaved, onError,
}: { data: BudgetOverview; onSaved: () => void; onError: (text: string) => void }) {
  return (
    <Card padded={false}>
      <div className="flex flex-wrap items-center gap-4 border-b px-4 py-2.5 text-xs text-[var(--text-muted)]"
           style={{ borderColor: 'var(--border)' }}>
        <span className="flex items-center gap-1.5">
          <svg width="18" height="8" aria-hidden><rect width="18" height="8" rx="4" fill="var(--series-1)" /></svg>
          {data.is_current ? 'Spent so far' : 'Spent'}
        </span>
        {data.is_current && (
          <span className="flex items-center gap-1.5">
            <svg width="18" height="8" aria-hidden>
              <rect x="0.75" y="0.75" width="16.5" height="6.5" rx="3.25" fill="none"
                    stroke="var(--series-1)" strokeWidth="1.5" />
            </svg>
            Projected
          </span>
        )}
        <span className="flex items-center gap-1.5">
          <svg width="4" height="14" aria-hidden><rect width="2" height="14" x="1" fill="var(--text-primary)" /></svg>
          State average
        </span>
        <span className="flex items-center gap-1.5">
          <svg width="4" height="14" aria-hidden>
            <line x1="2" x2="2" y1="0" y2="14" stroke="var(--text-muted)" strokeWidth="2" strokeDasharray="3 2" />
          </svg>
          Your budget
        </span>
      </div>

      <div className="overflow-x-auto">
        <table className="w-full min-w-[760px] text-sm">
          <thead>
            <tr className="text-left text-xs text-[var(--text-muted)]">
              <th className="px-4 py-2 font-medium">Category</th>
              <th className="px-2 py-2 font-medium">Budget</th>
              <th className="px-2 py-2 text-right font-medium">{data.is_current ? 'So far' : 'Spent'}</th>
              <th className="px-2 py-2 text-right font-medium">Typical month</th>
              <th className="px-2 py-2 text-right font-medium">State avg</th>
              <th className="px-2 py-2 text-right font-medium">vs state</th>
              <th className="px-4 py-2 font-medium" aria-hidden />
            </tr>
          </thead>
          <tbody>
            {data.categories.map((row) => (
              <Row key={row.category} row={row} isCurrent={data.is_current}
                   onSaved={onSaved} onError={onError} />
            ))}
          </tbody>
        </table>
      </div>
    </Card>
  )
}

function Row({
  row, isCurrent, onSaved, onError,
}: { row: BudgetRow; isCurrent: boolean; onSaved: () => void; onError: (t: string) => void }) {
  const basis = row.projected ?? row.spent
  return (
    <tr className="border-t" style={{ borderColor: 'var(--border)' }}>
      <td className="px-4 py-2.5">
        <div className="font-medium text-[var(--text-primary)]">{row.category}</div>
        {row.over_budget && (
          <div className="mt-0.5">
            <Badge tone="critical">{isCurrent ? 'Projected over budget' : 'Over budget'}</Badge>
          </div>
        )}
      </td>
      <td className="px-2 py-2.5">
        <BudgetInput category={row.category} value={row.budget} onSaved={onSaved} onError={onError} />
      </td>
      <td className="px-2 py-2.5 text-right tabular-nums text-[var(--text-primary)]">
        {money(row.spent, false)}
        {row.projected !== null && (
          <div className="text-xs text-[var(--text-muted)]">projected {money(row.projected, false)}</div>
        )}
      </td>
      <td className="px-2 py-2.5 text-right tabular-nums text-[var(--text-secondary)]">
        {row.typical === null ? '—' : money(row.typical, false)}
      </td>
      <td className="px-2 py-2.5 text-right tabular-nums text-[var(--text-secondary)]">
        {row.state === null ? (
          <span title={row.not_comparable_reason ?? undefined}
                className="inline-flex items-center gap-1 text-xs text-[var(--text-muted)]">
            <Info size={11} /> n/a
          </span>
        ) : money(row.state, false)}
      </td>
      <td className="px-2 py-2.5 text-right tabular-nums">
        {row.net_credit ? (
          <span className="text-xs text-[var(--text-muted)]"
                title="More came back than went out this month — refunds or reimbursements — so there is no spending to compare.">
            net credit
          </span>
        ) : row.vs_state_pct === null ? (
          <span className="text-[var(--text-muted)]">—</span>
        ) : (
          <span className="text-[var(--text-primary)]">
            {/* The arrow carries the direction, so the sign is never colour-alone. */}
            {row.vs_state_pct > 0 ? '▲' : row.vs_state_pct < 0 ? '▼' : '='}{' '}
            {signedPct(row.vs_state_pct)}
          </span>
        )}
      </td>
      <td className="px-4 py-2.5">
        <Bullet spent={row.spent} pace={row.projected} state={row.state} budget={row.budget}
                label={`${row.category}: ${money(basis, false)} against a state average of `
                       + `${row.state === null ? 'n/a' : money(row.state, false)}`} />
      </td>
    </tr>
  )
}

/** Spend as a bar; the state average and your budget as reference ticks. */
function Bullet({
  spent, pace, state, budget, label,
}: {
  spent: number; pace: number | null; state: number | null; budget: number | null; label: string
}) {
  const W = 160
  const H = 16
  const max = Math.max(spent, pace ?? 0, state ?? 0, budget ?? 0, 1) * 1.08
  const x = (v: number) => Math.max(0, Math.min(W, (v / max) * W))
  const barH = 8
  const y = (H - barH) / 2
  return (
    <svg width={W} height={H} role="img" aria-label={label} className="block">
      <title>{label}</title>
      <rect x={0} y={y} width={W} height={barH} rx={4} fill="var(--surface-2)" />
      {pace !== null && pace > spent && (
        <rect x={0.75} y={y + 0.75} width={Math.max(0, x(pace) - 1.5)} height={barH - 1.5} rx={3.25}
              fill="none" stroke="var(--series-1)" strokeWidth={1.5} />
      )}
      {spent > 0 && <rect x={0} y={y} width={Math.max(barH, x(spent))} height={barH} rx={4} fill="var(--series-1)" />}
      {budget !== null && budget > 0 && (
        <line x1={x(budget)} x2={x(budget)} y1={0} y2={H}
              stroke="var(--text-muted)" strokeWidth={2} strokeDasharray="3 2" />
      )}
      {state !== null && (
        <rect x={x(state) - 1} y={0} width={2} height={H} fill="var(--text-primary)" />
      )}
    </svg>
  )
}

/** Edits commit on blur or Enter, not per keystroke — one request per change. */
function BudgetInput({
  category, value, onSaved, onError,
}: { category: string; value: number | null; onSaved: () => void; onError: (t: string) => void }) {
  const [draft, setDraft] = useState(value === null ? '' : String(value))
  useEffect(() => setDraft(value === null ? '' : String(value)), [value])

  async function commit() {
    const next = draft.trim() === '' ? 0 : Number(draft)
    if (!Number.isFinite(next) || next < 0) {
      setDraft(value === null ? '' : String(value))
      return
    }
    if (next === (value ?? 0)) return
    try {
      await api.setBudget(category, next)
      onSaved()
    } catch (e) {
      onError(errorMessage(e))
    }
  }

  return (
    <div className="relative w-28">
      <span className="pointer-events-none absolute left-2 top-1/2 -translate-y-1/2 text-xs text-[var(--text-muted)]">$</span>
      <input
        inputMode="decimal"
        value={draft}
        placeholder="No budget"
        aria-label={`${category} monthly budget`}
        onChange={(e) => setDraft(e.target.value.replace(/[^0-9.]/g, ''))}
        onBlur={commit}
        onKeyDown={(e) => { if (e.key === 'Enter') (e.target as HTMLInputElement).blur() }}
        className="w-full rounded-md border bg-[var(--surface-1)] py-1 pl-5 pr-2 text-sm tabular-nums text-[var(--text-primary)] outline-none placeholder:text-[var(--text-muted)] focus:ring-2"
        style={{ borderColor: 'var(--border)' }}
      />
    </div>
  )
}

// ---------------------------------------------------------------------------
// 12-month grid
// ---------------------------------------------------------------------------

function HistoryGrid({
  data, selected, onSelect,
}: { data: BudgetOverview; selected: string; onSelect: (m: string) => void }) {
  const [hover, setHover] = useState<{ text: string; x: number; y: number } | null>(null)
  const now = currentMonth()
  const rows = useMemo(() => data.categories, [data])

  return (
    <Card padded={false}>
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1.5 border-b px-4 py-2.5 text-xs text-[var(--text-muted)]"
           style={{ borderColor: 'var(--border)' }}>
        <span>Compared with the {data.settings.state_name} average:</span>
        {LEGEND.map((l) => (
          <span key={l.label} className="flex items-center gap-1.5">
            <span className="inline-block h-3 w-3 rounded-sm" style={{ background: l.color }} aria-hidden />
            {l.label}
          </span>
        ))}
      </div>
      <div className="relative overflow-x-auto" onMouseLeave={() => setHover(null)}>
        <table className="w-full min-w-[860px] border-separate text-xs" style={{ borderSpacing: 2 }}>
          <thead>
            <tr>
              <th className="sticky left-0 z-10 bg-[var(--surface-1)] px-3 py-1.5 text-left font-medium text-[var(--text-muted)]">
                Category
              </th>
              {data.months.map((m) => (
                <th key={m} className="px-0.5 py-1.5 font-medium">
                  <button
                    onClick={() => onSelect(m)}
                    className="w-full rounded px-1 py-0.5 text-center"
                    style={{
                      color: m === selected ? 'var(--text-primary)' : 'var(--text-muted)',
                      background: m === selected ? 'var(--accent-wash)' : undefined,
                    }}
                  >
                    {monthShort(m)}
                    {m.endsWith('-01') && <span className="block text-[10px] opacity-70">{m.slice(0, 4)}</span>}
                  </button>
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <tr key={row.category}>
                <th className="sticky left-0 z-10 whitespace-nowrap bg-[var(--surface-1)] px-3 py-1 text-left font-medium text-[var(--text-secondary)]">
                  {row.category}
                </th>
                {row.history.map((h) => {
                  const running = h.month === now && data.is_current
                  // A running month is not tinted: its total is not a month yet.
                  const ratio = row.state && !running && h.spent > 0 ? h.spent / row.state : null
                  const fill = tint(ratio)
                  const tip = `${row.category} · ${monthLabel(h.month)}: ${money(h.spent, false)}`
                    + (running ? ' so far' : '')
                    + (ratio !== null ? ` — ${Math.round(ratio * 100)}% of the state average (${money(row.state, false)})` : '')
                    + (row.state === null ? ' — no comparable state figure' : '')
                  return (
                    <td key={h.month} className="p-0">
                      <button
                        onClick={() => onSelect(h.month)}
                        onMouseEnter={(e) => {
                          const box = (e.currentTarget.closest('.relative') as HTMLElement).getBoundingClientRect()
                          const cell = e.currentTarget.getBoundingClientRect()
                          setHover({ text: tip, x: cell.left - box.left + cell.width / 2, y: cell.top - box.top })
                        }}
                        onFocus={(e) => {
                          const box = (e.currentTarget.closest('.relative') as HTMLElement).getBoundingClientRect()
                          const cell = e.currentTarget.getBoundingClientRect()
                          setHover({ text: tip, x: cell.left - box.left + cell.width / 2, y: cell.top - box.top })
                        }}
                        onBlur={() => setHover(null)}
                        aria-label={tip}
                        className="h-8 w-full rounded px-1 text-center tabular-nums"
                        style={{
                          background: fill ?? 'transparent',
                          color: fill ? 'var(--div-ink)' : 'var(--text-secondary)',
                          fontStyle: running ? 'italic' : undefined,
                          outline: h.month === selected ? '2px solid var(--text-primary)' : undefined,
                          outlineOffset: -2,
                        }}
                      >
                        {h.spent !== 0 ? moneyCompact(h.spent) : '—'}
                      </button>
                    </td>
                  )
                })}
              </tr>
            ))}
          </tbody>
        </table>
        {hover && (
          <div
            className="pointer-events-none absolute z-20 max-w-xs -translate-x-1/2 -translate-y-full rounded-md border bg-[var(--surface-1)] px-2.5 py-1.5 text-xs text-[var(--text-primary)] shadow-lg"
            style={{ left: hover.x, top: hover.y - 6, borderColor: 'var(--border-strong)' }}
            role="tooltip"
          >
            {hover.text}
          </div>
        )}
      </div>
    </Card>
  )
}

// ---------------------------------------------------------------------------
// Where the state numbers come from
// ---------------------------------------------------------------------------

function Methodology({ data }: { data: BudgetOverview }) {
  const notComparable = data.categories.filter((r) => !r.comparable && r.not_comparable_reason)
  return (
    <Card className="mt-6">
      <CardHeader
        title="Where the state averages come from"
        subtitle={`${data.source.name}, ${data.source.year}.`}
      />
      <div className="space-y-2.5 text-xs leading-relaxed text-[var(--text-secondary)]">
        <p>
          BEA publishes what residents of each state spend per year, by type of spending. The app
          divides each figure by the state's population, then by twelve, then multiplies by your
          household size. That last step is a simplification — two people do not buy twice the
          internet — but it is far closer than comparing a couple against one person.
        </p>
        <p>
          BEA counts everything sold, rather than what households remember spending in a survey, so its
          figures run higher than survey-based averages. Housing includes the rent homeowners would pay
          for their own home, which makes it a fair yardstick for renters and owners alike.
        </p>
        <details>
          <summary className="cursor-pointer font-medium text-[var(--text-primary)]">
            Which BEA lines each category uses
          </summary>
          <ul className="mt-2 space-y-1">
            {Object.entries(data.source.lines).map(([category, lines]) => (
              <li key={category}>
                <span className="font-medium text-[var(--text-primary)]">{category}:</span>{' '}
                {lines.map((l) => l.description).join(' + ')}
              </li>
            ))}
          </ul>
        </details>
        {notComparable.length > 0 && (
          <div>
            <div className="mb-1 flex items-center gap-1 font-medium text-[var(--text-primary)]">
              <TriangleAlert size={12} /> Not compared, on purpose
            </div>
            <ul className="space-y-1">
              {notComparable.map((r) => (
                <li key={r.category}>
                  <span className="font-medium text-[var(--text-primary)]">{r.category}:</span>{' '}
                  {r.not_comparable_reason}
                </li>
              ))}
            </ul>
          </div>
        )}
        <p>
          <a href={data.source.url} target="_blank" rel="noreferrer" className="underline">
            Source data (BEA, SAPCE)
          </a>
        </p>
      </div>
    </Card>
  )
}
