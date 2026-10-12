/**
 * Buying a house — the goal tab.
 *
 * Everything a purchase actually requires, in the order it matters: can you
 * qualify, when will the cash be there, what will it cost every month, and is
 * buying even the better move at these numbers.
 *
 * The mortgage calculator appears twice on purpose. The figures tied to the
 * saved goal drive the plan; the quick calculator at the bottom prices any
 * house you come across without overwriting that plan.
 *
 * Dollar series share one axis throughout. Percentages — DTI, progress — are
 * meters, never a second y-axis on a dollar chart.
 */

import {
  Calculator, Check, CircleDashed, Info, MapPin, TriangleAlert, X,
} from 'lucide-react'
import { useEffect, useRef, useState } from 'react'
import { Link } from 'react-router-dom'

import { CompositionBar, MultiLine, StackedArea } from '../components/charts'
import {
  Badge, Banner, Card, CardHeader, DataTable, ErrorState, Field, Hero, LegendKey,
  Loading, Meter, NumberInput, SectionTitle, Segmented, Select, Slider, StatTile,
  money, moneyCompact,
} from '../components/ui'
import { useAsync, useDebounced } from '../hooks/useAsync'
import { api, errorMessage, type HouseGoal, type HousePlan, type LoanOption } from '../lib/api'
import { mediumDate, monthsToYears, pct } from '../lib/format'

const STATUS_ICON = {
  done: Check,
  on_track: CircleDashed,
  todo: CircleDashed,
  warn: TriangleAlert,
  blocked: X,
} as const

const STATUS_TONE = {
  done: 'good',
  on_track: 'info',
  todo: 'neutral',
  warn: 'warning',
  blocked: 'critical',
} as const

const STATUS_LABEL = {
  done: 'Done',
  on_track: 'On track',
  todo: 'To do',
  warn: 'Needs attention',
  blocked: 'Blocking',
} as const

const DTI_TONE = {
  comfortable: 'good',
  qualifies: 'info',
  stretched: 'warning',
  over_limit: 'critical',
  unknown: 'neutral',
} as const

const DTI_LABEL = {
  comfortable: 'Comfortable — inside 28/36',
  qualifies: 'Qualifies — inside the 43% QM limit',
  stretched: 'Stretched — past 43%, lenders will push back',
  over_limit: 'Over limit — above 50%',
  unknown: 'Income not set',
} as const

export default function House({ version }: { version: number }) {
  const [horizon, setHorizon] = useState(7)
  const [extra, setExtra] = useState(0)
  const [note, setNote] = useState<string | null>(null)

  const plan = useAsync<HousePlan>(
    () => api.housePlan({ horizon_years: horizon, extra_monthly: extra }),
    [horizon, extra, version],
  )

  // The editable assumptions are held locally so sliders stay responsive, and
  // saved on a debounce. The server's returned plan replaces the derived
  // figures, never the draft — otherwise the input would fight the user.
  const [draft, setDraft] = useState<HouseGoal | null>(null)
  const saveTimer = useRef<number | null>(null)

  useEffect(() => {
    if (plan.data && !draft) setDraft(plan.data.goal)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [plan.data])

  function edit<K extends keyof HouseGoal>(
    field: K, value: HouseGoal[K], applyStateDefaults = false,
  ) {
    if (!draft) return
    setDraft({ ...draft, [field]: value })
    if (saveTimer.current) window.clearTimeout(saveTimer.current)
    saveTimer.current = window.setTimeout(async () => {
      try {
        const updated = await api.updateHouseGoal({ [field]: value }, applyStateDefaults)
        plan.setData({
          ...updated,
          income_context: plan.data?.income_context ?? { available: false },
        })
        // A state change rewrites tax, insurance, and closing costs server-side,
        // so the local draft has to take those back or the inputs would show
        // the old values while the figures beside them show the new ones.
        setDraft(updated.goal)
        setNote(null)
      } catch (e) {
        setNote(errorMessage(e))
      }
    }, 400)
  }

  if (plan.loading) return <Loading label="Building your house plan" />
  if (plan.error) return <ErrorState message={plan.error} onRetry={plan.reload} />
  if (!plan.data || !draft) return null

  const p = plan.data
  const { payment, dti, cash_needed, projection, affordability, readiness, rent_vs_buy } = p
  const savedPct = cash_needed.total > 0 ? (p.goal.saved_amount / cash_needed.total) * 100 : 0

  return (
    <div className={plan.refreshing ? 'opacity-70 transition-opacity' : undefined}>
      {note && (
        <div className="mb-4">
          <Banner tone="critical" onDismiss={() => setNote(null)}>{note}</Banner>
        </div>
      )}

      {/* ---------------------------------------------------------------- */}
      <Card className="mb-4">
        <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_minmax(0,1fr)_minmax(0,2fr)]">
          <Field
            label="Where are you buying?"
            hint="Sets property tax, insurance, and closing costs to that state's averages."
          >
            <Select
              value={draft.state ?? ''}
              onChange={(code) => edit('state', code || null, true)}
              placeholder="Choose a state"
              options={p.states.map((st) => ({ value: st.code, label: st.name }))}
            />
          </Field>

          <Field label="Loan type" hint="Changes the insurance rules, not just the rate.">
            <Select
              value={draft.loan_type}
              onChange={(v) => edit('loan_type', v as HouseGoal['loan_type'])}
              options={[
                { value: 'conventional', label: 'Conventional' },
                { value: 'fha', label: 'FHA' },
                { value: 'va', label: 'VA' },
                { value: 'jumbo', label: 'Jumbo' },
              ]}
            />
          </Field>

          <div className="flex flex-col justify-center">
            {p.state ? (
              <div className="flex items-start gap-2 text-xs text-[var(--text-secondary)]">
                <MapPin size={13} className="mt-0.5 shrink-0 text-[var(--text-muted)]" />
                <div>
                  <span className="font-medium text-[var(--text-primary)]">{p.state.name}</span>
                  {' — '}
                  property tax {pct(p.state.property_tax_rate, 2)}, insurance about{' '}
                  {money(p.state.insurance_annual, false)}/yr, closing costs around{' '}
                  {pct(p.state.closing_cost_pct, 1)}. Median home{' '}
                  {moneyCompact(p.state.median_home_price)}.
                  <div className="mt-1 text-[var(--text-muted)]">
                    Statewide averages — your county and city rates are what actually
                    apply. Replace them with real quotes before making an offer.
                  </div>
                </div>
              </div>
            ) : (
              <p className="text-xs text-[var(--text-muted)]">
                Pick a state and the carrying costs below fill in. Property tax alone ranges
                from 0.29% in Hawaii to 2.23% in New Jersey — on an $800,000 house that is
                about $1,300 a month.
              </p>
            )}
          </div>
        </div>

        {p.state?.note && (
          <div className="mt-3">
            <Banner tone="info" title={`${p.state.name} specifics`}>{p.state.note}</Banner>
          </div>
        )}

        {payment.warnings.length > 0 && (
          <div className="mt-3 space-y-2">
            {payment.warnings.map((w) => (
              <Banner key={w} tone="warning">{w}</Banner>
            ))}
          </div>
        )}
      </Card>

      <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_minmax(0,2fr)]">
        <Card className="flex flex-col justify-between">
          <Hero
            label={`Monthly payment on ${moneyCompact(p.goal.target_price)}`}
            value={money(payment.total_monthly, false)}
            footnote={
              p.monthly_vs_rent >= 0
                ? `${money(p.monthly_vs_rent, false)} more than the ${money(p.goal.current_rent, false)} rent you pay now.`
                : `${money(Math.abs(p.monthly_vs_rent), false)} less than the ${money(p.goal.current_rent, false)} rent you pay now.`
            }
          />
          <div className="mt-4">
            <Badge tone={DTI_TONE[dti.verdict]}>{DTI_LABEL[dti.verdict]}</Badge>
          </div>
        </Card>

        <Card>
          <CardHeader
            title="What the payment is made of"
            subtitle="Principal and interest is the part a lower rate changes; the rest moves with the house"
          />
          <CompositionBar
            parts={[
              { label: 'Principal & interest', value: payment.principal_interest },
              { label: 'Property tax', value: payment.property_tax },
              { label: 'Insurance', value: payment.insurance },
              { label: 'PMI', value: payment.pmi },
              { label: 'HOA', value: payment.hoa },
            ]}
            total={payment.total_monthly}
            height={70}
          />
          <div className="mt-1">
            <LegendKey
              items={[
                { label: 'Principal & interest', colorIndex: 0, value: money(payment.principal_interest, false) },
                { label: 'Property tax', colorIndex: 1, value: money(payment.property_tax, false) },
                { label: 'Insurance', colorIndex: 2, value: money(payment.insurance, false) },
                ...(payment.pmi > 0
                  ? [{ label: 'PMI', colorIndex: 3, value: money(payment.pmi, false) }]
                  : []),
                ...(payment.hoa > 0
                  ? [{ label: 'HOA', colorIndex: 4, value: money(payment.hoa, false) }]
                  : []),
              ]}
            />
          </div>
          {payment.financed_fee > 0 && (
            <p className="mt-2 text-xs text-[var(--text-muted)]">
              {payment.fee_label} of {money(payment.financed_fee, false)} is financed into the
              loan, so you borrow {money(payment.loan_amount, false)} rather than{' '}
              {money(payment.base_loan, false)} — the payment above reflects the larger figure.
            </p>
          )}
          {payment.pmi > 0 && (
            <p className="mt-2 text-xs text-[var(--text-muted)]">
              {payment.mi_rule === 'never' ? (
                <>
                  FHA mortgage insurance of {money(payment.pmi, false)}/mo runs for the{' '}
                  <strong>life of the loan</strong> at this down payment —{' '}
                  {money(p.schedule_summary.total_pmi, false)} in total. Conventional PMI would
                  stop around 78% loan-to-value; escaping FHA's means refinancing.
                </>
              ) : payment.mi_rule.startsWith('months:') ? (
                <>
                  FHA mortgage insurance of {money(payment.pmi, false)}/mo runs for 11 years —{' '}
                  {money(p.schedule_summary.total_pmi, false)} in total.
                </>
              ) : (
                <>
                  PMI of {money(payment.pmi, false)}/mo applies while you owe more than 80% of
                  the value. It can be requested away at month{' '}
                  {p.schedule_summary.pmi_request_month} and drops automatically at month{' '}
                  {p.schedule_summary.pmi_ends_month} —{' '}
                  {money(p.schedule_summary.total_pmi, false)} in total.
                </>
              )}
            </p>
          )}
        </Card>
      </div>

      {/* ---------------------------------------------------------------- */}
      <SectionTitle hint="The four things a lender looks at, and the one thing they do not: whether you still have money afterwards.">
        Readiness
      </SectionTitle>
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        {readiness.checks.map((check) => {
          const Icon = STATUS_ICON[check.status]
          return (
            <Card key={check.label}>
              <div className="flex items-start justify-between gap-2">
                <span className="text-xs font-medium text-[var(--text-secondary)]">
                  {check.label}
                </span>
                <Badge tone={STATUS_TONE[check.status]}>
                  <Icon size={10} strokeWidth={3} />
                  {STATUS_LABEL[check.status]}
                </Badge>
              </div>
              <div className="mt-2.5">
                <Meter
                  value={check.progress}
                  max={100}
                  height={6}
                  severity={
                    check.status === 'done' ? 'good'
                      : check.status === 'blocked' ? 'critical'
                        : check.status === 'warn' ? 'warning' : 'accent'
                  }
                />
              </div>
              <p className="mt-2 text-xs leading-relaxed text-[var(--text-muted)]">
                {check.detail}
              </p>
            </Card>
          )
        })}
      </div>

      {/* ---------------------------------------------------------------- */}
      <SectionTitle hint="Down payment plus closing costs — the number that actually has to be in the bank.">
        The down payment fund
      </SectionTitle>
      <div className="grid gap-4 lg:grid-cols-[minmax(0,3fr)_minmax(0,2fr)]">
        <Card>
          <CardHeader
            title={`${money(p.goal.saved_amount, false)} of ${money(cash_needed.total, false)}`}
            subtitle={
              p.goal.saved_from_accounts
                ? 'Read live from the accounts you nominated below'
                : 'Typed in manually — nominate an account below to track it automatically'
            }
            action={<Badge tone={savedPct >= 100 ? 'good' : 'info'}>{pct(savedPct, 0)}</Badge>}
          />
          <Meter
            value={p.goal.saved_amount}
            max={cash_needed.total}
            height={12}
            severity={savedPct >= 100 ? 'good' : 'accent'}
          />
          <div className="mt-4 grid gap-3 sm:grid-cols-3">
            <div>
              <div className="text-xs text-[var(--text-muted)]">Down payment</div>
              <div className="tnum text-sm font-semibold">{money(cash_needed.down_payment, false)}</div>
            </div>
            <div>
              <div className="text-xs text-[var(--text-muted)]">Closing costs</div>
              <div className="tnum text-sm font-semibold">{money(cash_needed.closing_costs, false)}</div>
            </div>
            <div>
              <div className="text-xs text-[var(--text-muted)]">Still to save</div>
              <div className="tnum text-sm font-semibold">{money(projection.shortfall, false)}</div>
            </div>
          </div>
          <div className="mt-4 grid gap-3 sm:grid-cols-2">
            <Field label="Monthly contribution">
              <NumberInput
                value={draft.monthly_contribution}
                prefix="$"
                step={100}
                min={0}
                onChange={(v) => edit('monthly_contribution', v)}
              />
            </Field>
            <Field label="Savings APY" hint="Apple Savings pays about 4%; checking pays nothing.">
              <NumberInput
                value={draft.savings_apy}
                suffix="%"
                step={0.05}
                min={0}
                onChange={(v) => edit('savings_apy', v)}
              />
            </Field>
          </div>
        </Card>

        <Card>
          <CardHeader
            title="When the money is there"
            subtitle={`At ${money(p.goal.monthly_contribution, false)}/mo plus ${pct(p.goal.savings_apy, 2)} interest`}
          />
          {projection.reachable && projection.months !== null ? (
            <>
              <div className="text-3xl font-semibold leading-none">
                {monthsToYears(projection.months)}
              </div>
              <p className="mt-1 text-sm text-[var(--text-secondary)]">
                ready around {mediumDate(projection.target_date)}
              </p>
              <p className="mt-2 text-xs text-[var(--text-muted)]">
                Of the {money(projection.shortfall, false)} still needed,{' '}
                {money(projection.projected_interest, false)} comes from interest rather than from
                you.
              </p>
            </>
          ) : (
            <Banner tone="warning">
              With no monthly contribution and no yield, this target is never reached. Set a
              contribution above.
            </Banner>
          )}

          {p.savings_impact.available && p.savings_impact.options?.length ? (
            <div className="mt-4 border-t pt-3" style={{ borderColor: 'var(--border)' }}>
              <div className="mb-2 text-xs font-semibold text-[var(--text-secondary)]">
                If you redirect what the Savings tab found
              </div>
              <div className="space-y-2">
                {p.savings_impact.options.map((option) => (
                  <div key={option.label} className="flex items-baseline justify-between gap-2">
                    <div className="min-w-0">
                      <div className="text-xs font-medium text-[var(--text-primary)]">
                        {option.label}
                      </div>
                      <div className="text-xs text-[var(--text-muted)]">
                        +{money(option.extra_monthly, false)}/mo
                      </div>
                    </div>
                    <div className="shrink-0 text-right">
                      <div className="tnum text-xs font-semibold"
                           style={{ color: option.months_saved ? 'var(--success-text)' : undefined }}>
                        {option.months_saved ? `${option.months_saved} mo sooner` : 'no change'}
                      </div>
                      <div className="tnum text-xs text-[var(--text-muted)]">
                        {mediumDate(option.target_date)}
                      </div>
                    </div>
                  </div>
                ))}
              </div>
              <Link
                to="/savings"
                className="mt-2 inline-flex items-center gap-1 text-xs font-medium text-[var(--text-secondary)] hover:text-[var(--text-primary)]"
              >
                <Info size={12} /> See where that money comes from
              </Link>
            </div>
          ) : null}
        </Card>
      </div>

      {/* ---------------------------------------------------------------- */}
      <SectionTitle hint="Two separate ceilings. Lenders cap what you can borrow; your savings cap what you can put down. The lower one is your real budget.">
        What you can afford today
      </SectionTitle>
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <StatTile
          label="Your real budget"
          value={moneyCompact(affordability.max_price)}
          sub={`Limited by ${affordability.limited_by === 'cash' ? 'cash on hand' : 'income'}`}
          accent
        />
        <StatTile
          label="Income allows"
          value={moneyCompact(affordability.price_by_income)}
          sub={`${money(affordability.monthly_budget, false)}/mo of housing at a 36% back-end ratio`}
        />
        <StatTile
          label="Cash allows"
          value={moneyCompact(affordability.price_by_cash)}
          sub={`${pct(p.goal.down_payment_pct, 0)} down plus ${pct(p.goal.closing_cost_pct, 1)} closing`}
        />
        <StatTile
          label="Your target"
          value={moneyCompact(p.goal.target_price)}
          sub={
            p.goal.target_price > affordability.max_price
              ? `${moneyCompact(p.goal.target_price - affordability.max_price)} above today's ceiling`
              : 'Inside what you can afford today'
          }
        />
      </div>

      <Card className="mt-4">
        <CardHeader
          title="Debt-to-income"
          subtitle="The ratio that decides approval. Front-end is housing alone; back-end adds every other monthly debt."
        />
        <div className="grid gap-5 sm:grid-cols-2">
          <div>
            <Meter
              label="Front-end — housing ÷ gross income"
              value={dti.front_end}
              max={43}
              right={`${pct(dti.front_end)} of ${pct(28, 0)} target`}
              severity={dti.front_end <= 28 ? 'good' : dti.front_end <= 36 ? 'warning' : 'critical'}
            />
            <p className="mt-1.5 text-xs text-[var(--text-muted)]">
              {money(payment.piti, false)} of housing against {money(dti.gross_monthly, false)}/mo
              gross.
            </p>
          </div>
          <div>
            <Meter
              label="Back-end — all debt ÷ gross income"
              value={dti.back_end}
              max={50}
              right={`${pct(dti.back_end)} · QM caps at 43%`}
              severity={dti.back_end <= 36 ? 'good' : dti.back_end <= 43 ? 'warning' : 'critical'}
            />
            <p className="mt-1.5 text-xs text-[var(--text-muted)]">
              {dti.headroom >= 0
                ? `${money(dti.headroom, false)}/mo of headroom below the conventional 36% line.`
                : `${money(Math.abs(dti.headroom), false)}/mo above the conventional 36% line.`}
            </p>
          </div>
        </div>
      </Card>

      {/* ---------------------------------------------------------------- */}
      <SectionTitle hint="Both series are dollars, so they share one axis. The crossover is the month your stake in the house finally exceeds what the loan has cost you.">
        Equity against interest paid
      </SectionTitle>
      <Card>
        <CardHeader
          title="Over the life of the loan"
          subtitle={`${money(p.schedule_summary.total_interest, false)} of interest over ${p.schedule_summary.payoff_years} years, on a ${moneyCompact(payment.loan_amount)} loan`}
          action={
            <Segmented
              size="sm"
              value={extra}
              onChange={setExtra}
              options={[
                { value: 0, label: 'As scheduled' },
                { value: 250, label: '+$250/mo' },
                { value: 500, label: '+$500/mo' },
                { value: 1000, label: '+$1,000/mo' },
              ]}
            />
          }
        />
        {p.equity_by_year.length > 1 && (
          <MultiLine
            labels={p.equity_by_year.map((y) => `Year ${y.year}`)}
            series={[
              { name: 'Your equity', values: p.equity_by_year.map((y) => y.equity), colorIndex: 0 },
              { name: 'Interest paid so far', values: p.equity_by_year.map((y) => y.cumulative_interest), colorIndex: 1 },
              { name: 'Still owed', values: p.equity_by_year.map((y) => y.balance), colorIndex: 6 },
            ]}
            height={300}
          />
        )}
        {extra > 0 && (
          <div className="mt-3">
            <Banner tone="good" title={`Paying ${money(extra, false)} extra each month`}>
              The loan clears in {p.schedule_summary.payoff_years} years instead of{' '}
              {p.goal.loan_term_years}, and total interest falls to{' '}
              {money(p.schedule_summary.total_interest, false)}.
            </Banner>
          </div>
        )}
      </Card>

      {/* ---------------------------------------------------------------- */}
      <SectionTitle hint="The monthly payment and the lifetime cost rank these differently, which is the whole reason to look at both.">
        Loan programs compared
      </SectionTitle>
      <Card>
        <DataTable
          columns={[
            {
              key: 'label',
              header: 'Program',
              render: (o: LoanOption) => (
                <div>
                  <div className="flex items-center gap-1.5">
                    <span className="font-medium text-[var(--text-primary)]">{o.label}</span>
                    {o.selected && <Badge tone="info">selected</Badge>}
                  </div>
                  {/* Without this, "Jumbo costs the same as conventional" reads as a
                      finding rather than as a sign the loan is not a jumbo at all. */}
                  {o.warnings.map((w) => (
                    <div
                      key={w}
                      className="mt-1 flex max-w-md items-start gap-1 text-xs"
                      style={{ color: 'var(--text-muted)' }}
                    >
                      <TriangleAlert
                        size={11}
                        className="mt-0.5 shrink-0"
                        style={{ color: 'var(--status-warning)' }}
                      />
                      <span>{w}</span>
                    </div>
                  ))}
                </div>
              ),
            },
            { key: 'monthly', header: 'Monthly', align: 'right', numeric: true,
              render: (o) => <span className="font-semibold">{money(o.monthly, false)}</span> },
            { key: 'mi', header: 'Mortgage insurance', align: 'right', numeric: true,
              render: (o) => (
                <div className="whitespace-nowrap">
                  <div>{o.mortgage_insurance > 0 ? `${money(o.mortgage_insurance, false)}/mo` : 'None'}</div>
                  <div className="text-xs text-[var(--text-muted)]">
                    {o.mi_rule === 'never' ? 'for the life of the loan'
                      : o.mi_rule.startsWith('months:') ? '11 years'
                        : o.mi_rule === 'ltv78' ? 'until 78% LTV' : '—'}
                  </div>
                </div>) },
            { key: 'fee', header: 'Financed fee', align: 'right', numeric: true,
              render: (o) => (
                <span className="text-[var(--text-secondary)]">
                  {o.financed_fee > 0 ? money(o.financed_fee, false) : '—'}
                </span>) },
            { key: 'cash', header: 'Cash at closing', align: 'right', numeric: true,
              render: (o) => <span>{money(o.cash_needed, false)}</span> },
            { key: 'lifetime', header: 'Interest + insurance', align: 'right', numeric: true,
              render: (o) => (
                <span className="font-semibold">{moneyCompact(o.lifetime_cost)}</span>) },
            {
              key: 'pick',
              header: '',
              align: 'right',
              render: (o: LoanOption) =>
                o.selected ? null : (
                  <button
                    onClick={() => edit('loan_type', o.loan_type)}
                    className="whitespace-nowrap text-xs font-medium hover:underline"
                    style={{ color: 'var(--series-1)' }}
                  >
                    use this
                  </button>
                ),
            },
          ]}
          rows={p.loan_comparison}
          rowKey={(o) => o.loan_type}
        />
        <p className="mt-3 text-xs leading-relaxed text-[var(--text-muted)]">
          All four price the same {money(p.goal.target_price, false)} house at{' '}
          {pct(p.goal.down_payment_pct, 1)} down and {pct(p.goal.interest_rate, 2)}. In practice
          each program carries a slightly different rate, so treat the gaps as directional.
          FHA is the one to read carefully: its monthly insurance is often the{' '}
          <em>lowest</em> here while its lifetime cost is the highest, because below 10% down
          the premium never falls away. VA is available only to eligible service members and
          veterans. Jumbo applies above the{' '}
          {money(p.goal.conforming_limit, false)} conforming limit (the 2025 baseline — high-cost
          counties are higher, and it rises most years).
        </p>
      </Card>

      <SectionTitle hint="Each row is a different plan, not just a cheaper one — a smaller down payment buys years off the waiting, at the cost of PMI and a bigger payment.">
        Down payment scenarios
      </SectionTitle>
      <Card>
        <DataTable
          columns={[
            { key: 'label', header: 'Scenario',
              render: (s) => <span className="font-medium text-[var(--text-primary)]">{s.label}</span> },
            { key: 'monthly', header: 'Monthly', align: 'right', numeric: true,
              render: (s) => <span className="font-semibold">{money(s.monthly, false)}</span> },
            { key: 'pmi', header: 'of which PMI', align: 'right', numeric: true,
              render: (s) => (
                <span className="text-[var(--text-muted)]">
                  {s.pmi > 0 ? money(s.pmi, false) : '—'}
                </span>) },
            { key: 'cash', header: 'Cash at closing', align: 'right', numeric: true,
              render: (s) => <span>{money(s.cash_needed, false)}</span> },
            { key: 'wait', header: 'Wait', align: 'right', numeric: true,
              render: (s) => (
                <span className="whitespace-nowrap">
                  {s.months_to_save !== null ? monthsToYears(s.months_to_save) : '—'}
                  {s.ready_date && (
                    <span className="ml-1 text-xs text-[var(--text-muted)]">
                      {mediumDate(s.ready_date)}
                    </span>
                  )}
                </span>) },
            { key: 'interest', header: 'Lifetime interest', align: 'right', numeric: true,
              render: (s) => <span className="text-[var(--text-secondary)]">{moneyCompact(s.total_interest)}</span> },
            { key: 'dti', header: 'Back-end DTI', align: 'right', numeric: true,
              render: (s) => (
                <Badge tone={DTI_TONE[s.verdict as keyof typeof DTI_TONE]}>
                  {pct(s.back_end_dti)}
                </Badge>) },
          ]}
          rows={p.scenarios}
          rowKey={(s) => s.label}
        />
        <p className="mt-3 text-xs text-[var(--text-muted)]">
          All rows price the same {money(p.goal.target_price, false)} house. “Wait” is how long the
          cash takes at your current contribution and APY.
        </p>
      </Card>

      {/* ---------------------------------------------------------------- */}
      <SectionTitle hint="The comparison most calculators get wrong: the renter invests the cash a buyer sinks into the down payment, and that opportunity cost is usually the deciding factor.">
        Buying against renting
      </SectionTitle>
      <Card>
        <CardHeader
          title={
            rent_vs_buy.verdict === 'buy'
              ? `Buying comes out ${moneyCompact(Math.abs(rent_vs_buy.advantage))} ahead over ${horizon} years`
              : `Renting comes out ${moneyCompact(Math.abs(rent_vs_buy.advantage))} ahead over ${horizon} years`
          }
          subtitle={
            rent_vs_buy.breakeven_year
              ? `Buying pulls ahead in year ${rent_vs_buy.breakeven_year}.`
              : `Buying does not pull ahead within ${horizon} years at these assumptions.`
          }
          action={
            <Segmented
              size="sm"
              value={horizon}
              onChange={setHorizon}
              options={[
                { value: 5, label: '5 yr' },
                { value: 7, label: '7 yr' },
                { value: 10, label: '10 yr' },
                { value: 15, label: '15 yr' },
                { value: 30, label: '30 yr' },
              ]}
            />
          }
        />
        <MultiLine
          labels={rent_vs_buy.yearly.map((y) => `Year ${y.year}`)}
          series={[
            { name: 'Buying — equity after selling costs', values: rent_vs_buy.yearly.map((y) => y.buyer_net_worth), colorIndex: 0 },
            { name: 'Renting — invested instead', values: rent_vs_buy.yearly.map((y) => y.renter_net_worth), colorIndex: 1 },
          ]}
          height={300}
        />
        <div className="mt-4 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          <StatTile label="Buying, after selling costs" value={moneyCompact(rent_vs_buy.buyer_net_worth)} />
          <StatTile label="Renting, invested" value={moneyCompact(rent_vs_buy.renter_net_worth)} />
          <StatTile label="Spent on housing, buying" value={moneyCompact(rent_vs_buy.total_spent_buying)} />
          <StatTile label="Spent on rent" value={moneyCompact(rent_vs_buy.total_spent_renting)} />
        </div>
        <p className="mt-3 text-xs leading-relaxed text-[var(--text-muted)]">
          Buying assumes {pct(p.goal.home_appreciation, 1)} appreciation, 1%/yr maintenance, and 6%
          in selling costs on exit, with the mortgage-interest and property-tax deduction credited
          only above the standard deduction and with property tax capped at the $10,000 SALT limit.
          Renting assumes the down payment and closing costs are invested at{' '}
          {pct(p.goal.investment_return, 1)}, plus any monthly difference in housing cost, with rent
          rising {pct(p.goal.rent_inflation, 1)} a year. A high price-to-rent ratio favours renting;
          change the assumptions below to test that.
        </p>
      </Card>

      {/* ---------------------------------------------------------------- */}
      <QuickCalculator goal={p.goal} />

      {/* ---------------------------------------------------------------- */}
      <SectionTitle hint="Everything above is derived from these. Changes save as you make them.">
        Assumptions
      </SectionTitle>
      <Card>
        <div className="grid gap-5 lg:grid-cols-3">
          <div className="space-y-4">
            <div className="text-xs font-semibold uppercase tracking-wide text-[var(--text-muted)]">
              The house
            </div>
            <Slider
              label="Target price"
              display={money(draft.target_price, false)}
              value={draft.target_price}
              min={150_000}
              max={3_000_000}
              step={25_000}
              onChange={(v) => edit('target_price', v)}
            />
            <Slider
              label="Down payment"
              display={`${pct(draft.down_payment_pct, 0)} · ${money(draft.target_price * draft.down_payment_pct / 100, false)}`}
              value={draft.down_payment_pct}
              min={0}
              max={50}
              step={0.5}
              onChange={(v) => edit('down_payment_pct', v)}
            />
            <Slider
              label="Interest rate"
              display={pct(draft.interest_rate, 2)}
              value={draft.interest_rate}
              min={2}
              max={12}
              step={0.05}
              onChange={(v) => edit('interest_rate', v)}
            />
            <Field label="Loan term">
              <Segmented
                value={draft.loan_term_years}
                onChange={(v) => edit('loan_term_years', v)}
                options={[
                  { value: 15, label: '15 years' },
                  { value: 20, label: '20 years' },
                  { value: 30, label: '30 years' },
                ]}
              />
            </Field>
          </div>

          <div className="space-y-4">
            <div className="text-xs font-semibold uppercase tracking-wide text-[var(--text-muted)]">
              Carrying costs
            </div>
            <Field label="Property tax rate" hint="Roughly 1.1–1.3% of price in most of California.">
              <NumberInput
                value={draft.property_tax_rate}
                suffix="% / yr"
                step={0.05}
                min={0}
                onChange={(v) => edit('property_tax_rate', v)}
              />
            </Field>
            <Field label="Homeowner's insurance">
              <NumberInput
                value={draft.insurance_annual}
                prefix="$"
                suffix="/ yr"
                step={100}
                min={0}
                onChange={(v) => edit('insurance_annual', v)}
              />
            </Field>
            <Field label="HOA dues">
              <NumberInput
                value={draft.hoa_monthly}
                prefix="$"
                suffix="/ mo"
                step={25}
                min={0}
                onChange={(v) => edit('hoa_monthly', v)}
              />
            </Field>
            <Field label="PMI rate" hint="Charged only above 80% loan-to-value. 0.3–1.2% by credit score.">
              <NumberInput
                value={draft.pmi_rate}
                suffix="% / yr"
                step={0.05}
                min={0}
                onChange={(v) => edit('pmi_rate', v)}
              />
            </Field>
            <Field label="Closing costs" hint="2–5% of price: lender fees, title, escrow, prepaids.">
              <NumberInput
                value={draft.closing_cost_pct}
                suffix="% of price"
                step={0.25}
                min={0}
                onChange={(v) => edit('closing_cost_pct', v)}
              />
            </Field>
            <Field
              label="Conforming loan limit"
              hint="Above this a loan prices as a jumbo. 2025 baseline; high-cost counties are higher."
            >
              <NumberInput
                value={draft.conforming_limit}
                prefix="$"
                step={10_000}
                min={1}
                onChange={(v) => edit('conforming_limit', v)}
              />
            </Field>
          </div>

          <div className="space-y-4">
            <div className="text-xs font-semibold uppercase tracking-wide text-[var(--text-muted)]">
              You
            </div>
            <Field
              label="Gross annual income"
              hint={
                p.income_context.available
                  ? `Your deposits suggest about ${money((p.income_context.median_monthly_income ?? 0) * 12, false)}/yr.`
                  : undefined
              }
            >
              <NumberInput
                value={draft.gross_annual_income}
                prefix="$"
                step={5000}
                min={0}
                onChange={(v) => edit('gross_annual_income', v)}
              />
            </Field>
            <Field label="Other monthly debt" hint="Car, student loans, card minimums — not rent.">
              <NumberInput
                value={draft.monthly_debts}
                prefix="$"
                suffix="/ mo"
                step={50}
                min={0}
                onChange={(v) => edit('monthly_debts', v)}
              />
            </Field>
            <Slider
              label="Credit score"
              display={String(draft.credit_score)}
              value={draft.credit_score}
              min={580}
              max={850}
              step={1}
              onChange={(v) => edit('credit_score', v)}
            />
            <Field label="Current rent">
              <NumberInput
                value={draft.current_rent}
                prefix="$"
                suffix="/ mo"
                step={100}
                min={0}
                onChange={(v) => edit('current_rent', v)}
              />
            </Field>
            <Field label="Marginal tax rate" hint="Drives the value of the interest deduction.">
              <NumberInput
                value={draft.marginal_tax_rate}
                suffix="%"
                step={1}
                min={0}
                onChange={(v) => edit('marginal_tax_rate', v)}
              />
            </Field>
          </div>
        </div>

        <div className="mt-5 grid gap-5 border-t pt-5 lg:grid-cols-3" style={{ borderColor: 'var(--border)' }}>
          <Field label="Home appreciation" hint="Long-run US average is around 3–4%.">
            <NumberInput
              value={draft.home_appreciation}
              suffix="% / yr"
              step={0.25}
              onChange={(v) => edit('home_appreciation', v)}
            />
          </Field>
          <Field label="Investment return" hint="What the renter's invested down payment earns.">
            <NumberInput
              value={draft.investment_return}
              suffix="% / yr"
              step={0.25}
              onChange={(v) => edit('investment_return', v)}
            />
          </Field>
          <Field label="Rent inflation">
            <NumberInput
              value={draft.rent_inflation}
              suffix="% / yr"
              step={0.25}
              onChange={(v) => edit('rent_inflation', v)}
            />
          </Field>
        </div>
      </Card>
    </div>
  )
}

/**
 * A standalone calculator for any house you come across, deliberately separate
 * from the saved goal so pricing a listing does not rewrite the plan.
 */
function QuickCalculator({ goal }: { goal: HouseGoal }) {
  const [price, setPrice] = useState(goal.target_price)
  const [downPct, setDownPct] = useState(goal.down_payment_pct)
  const [rate, setRate] = useState(goal.interest_rate)
  const [term, setTerm] = useState(goal.loan_term_years)
  const [extraMonthly, setExtraMonthly] = useState(0)
  const [taxRate, setTaxRate] = useState(goal.property_tax_rate)
  const [hoa, setHoa] = useState(goal.hoa_monthly)
  const [loanType, setLoanType] = useState(goal.loan_type)

  // The controls stay fully responsive; only the request waits for the drag to
  // settle. Without this a slider issues a request per frame.
  const q = {
    price: useDebounced(price),
    downPct: useDebounced(downPct),
    rate: useDebounced(rate),
    term: useDebounced(term),
    taxRate: useDebounced(taxRate),
    hoa: useDebounced(hoa),
    extraMonthly: useDebounced(extraMonthly),
    loanType: useDebounced(loanType),
  }

  const quote = useAsync(
    () => api.mortgageQuote({
      home_price: q.price,
      down_payment_pct: q.downPct,
      interest_rate: q.rate,
      loan_term_years: q.term,
      property_tax_rate: q.taxRate,
      insurance_annual: goal.insurance_annual,
      hoa_monthly: q.hoa,
      pmi_rate: goal.pmi_rate,
      closing_cost_pct: goal.closing_cost_pct,
      gross_annual_income: goal.gross_annual_income,
      monthly_debts: goal.monthly_debts,
      extra_monthly: q.extraMonthly,
      loan_type: q.loanType,
      conforming_limit: goal.conforming_limit,
      va_first_use: Boolean(goal.va_first_use),
    }),
    [q.price, q.downPct, q.rate, q.term, q.taxRate, q.hoa, q.extraMonthly, q.loanType],
  )

  return (
    <>
      <SectionTitle hint="Price a specific listing without touching the plan above.">
        Mortgage calculator
      </SectionTitle>
      <Card>
        <div className="grid gap-5 lg:grid-cols-[minmax(0,1fr)_minmax(0,2fr)]">
          <div className="space-y-4">
            <Field label="Home price">
              <NumberInput value={price} prefix="$" step={10_000} min={1} onChange={setPrice} />
            </Field>
            <Slider
              label="Down payment"
              display={`${pct(downPct, 1)} · ${money(price * downPct / 100, false)}`}
              value={downPct}
              min={0}
              max={50}
              step={0.5}
              onChange={setDownPct}
            />
            <Slider
              label="Interest rate"
              display={pct(rate, 2)}
              value={rate}
              min={2}
              max={12}
              step={0.05}
              onChange={setRate}
            />
            <Field label="Term">
              <Segmented
                value={term}
                onChange={setTerm}
                options={[
                  { value: 15, label: '15 yr' },
                  { value: 20, label: '20 yr' },
                  { value: 30, label: '30 yr' },
                ]}
              />
            </Field>
            <Field label="Loan type">
              <Select
                value={loanType}
                onChange={(v) => setLoanType(v as typeof loanType)}
                options={[
                  { value: 'conventional', label: 'Conventional' },
                  { value: 'fha', label: 'FHA' },
                  { value: 'va', label: 'VA' },
                  { value: 'jumbo', label: 'Jumbo' },
                ]}
              />
            </Field>
            <div className="grid grid-cols-2 gap-3">
              <Field label="Property tax">
                <NumberInput value={taxRate} suffix="%" step={0.05} min={0} onChange={setTaxRate} />
              </Field>
              <Field label="HOA">
                <NumberInput value={hoa} prefix="$" step={25} min={0} onChange={setHoa} />
              </Field>
            </div>
            <Field label="Extra principal each month" hint="Applied on top of the scheduled payment.">
              <NumberInput
                value={extraMonthly}
                prefix="$"
                step={100}
                min={0}
                onChange={setExtraMonthly}
              />
            </Field>
          </div>

          <div>
            {quote.loading && <Loading label="Calculating" />}
            {quote.error && <Banner tone="critical">{quote.error}</Banner>}
            {quote.data && (
              <div className={quote.refreshing ? 'opacity-70 transition-opacity' : undefined}>
                <div className="flex flex-wrap items-end justify-between gap-4">
                  <div>
                    <div className="flex items-center gap-1.5 text-xs font-medium text-[var(--text-muted)]">
                      <Calculator size={12} /> Total monthly payment
                    </div>
                    <div className="mt-0.5 text-4xl font-semibold leading-none">
                      {money(quote.data.payment.total_monthly, false)}
                    </div>
                  </div>
                  {quote.data.dti && (
                    <Badge tone={DTI_TONE[quote.data.dti.verdict as keyof typeof DTI_TONE]}>
                      {pct(quote.data.dti.back_end)} back-end DTI
                    </Badge>
                  )}
                </div>

                <div className="mt-4 grid gap-3 sm:grid-cols-3">
                  <StatTile
                    label="Loan amount"
                    value={moneyCompact(quote.data.payment.loan_amount)}
                    sub={`${pct(quote.data.payment.ltv, 1)} loan-to-value`}
                  />
                  <StatTile
                    label="Cash at closing"
                    value={moneyCompact(quote.data.cash_needed.total)}
                    sub={`${money(quote.data.cash_needed.down_payment, false)} down + ${money(quote.data.cash_needed.closing_costs, false)} costs`}
                  />
                  <StatTile
                    label="Lifetime interest"
                    value={moneyCompact(quote.data.totals.total_interest)}
                    sub={`Paid off in ${quote.data.totals.payoff_years} years`}
                  />
                </div>

                <div className="mt-4">
                  <CompositionBar
                    parts={[
                      { label: 'Principal & interest', value: quote.data.payment.principal_interest },
                      { label: 'Property tax', value: quote.data.payment.property_tax },
                      { label: 'Insurance', value: quote.data.payment.insurance },
                      { label: 'PMI', value: quote.data.payment.pmi },
                      { label: 'HOA', value: quote.data.payment.hoa },
                    ]}
                    total={quote.data.payment.total_monthly}
                    height={66}
                  />
                </div>

                {quote.data.payment.warnings?.length > 0 && (
                  <div className="mt-3 space-y-2">
                    {quote.data.payment.warnings.map((w: string) => (
                      <Banner key={w} tone="warning">{w}</Banner>
                    ))}
                  </div>
                )}

                {quote.data.extra_payment_effect && (
                  <div className="mt-3">
                    <Banner
                      tone="good"
                      title={`${money(q.extraMonthly, false)} extra saves ${moneyCompact(quote.data.extra_payment_effect.interest_saved)} in interest`}
                    >
                      Paid off in {quote.data.extra_payment_effect.payoff_years} years instead of{' '}
                      {quote.data.extra_payment_effect.baseline_payoff_years} —{' '}
                      {monthsToYears(quote.data.extra_payment_effect.months_saved)} earlier.
                    </Banner>
                  </div>
                )}

                <div className="mt-4">
                  <CardHeader
                    title="Where each year's payments go"
                    subtitle="Interest dominates early; the crossover is later than most people expect"
                  />
                  <StackedArea
                    labels={quote.data.yearly.map((y: { year: number }) => y.year)}
                    xName="Year"
                    series={[
                      { name: 'Interest', values: quote.data.yearly.map((y: { interest: number }) => y.interest), colorIndex: 1 },
                      { name: 'Principal', values: quote.data.yearly.map((y: { principal: number }) => y.principal), colorIndex: 0 },
                      ...(quote.data.totals.total_pmi > 0
                        ? [{ name: 'PMI', values: quote.data.yearly.map((y: { pmi: number }) => y.pmi), colorIndex: 3 }]
                        : []),
                    ]}
                    height={250}
                  />
                </div>

                {quote.data.affordability && (
                  <p className="mt-3 text-xs text-[var(--text-muted)]">
                    On {money(goal.gross_annual_income, false)} of income with{' '}
                    {money(goal.monthly_debts, false)}/mo of other debt, a 36% back-end ratio
                    supports about {moneyCompact(quote.data.affordability.price_by_income)} at this
                    rate and down payment.
                  </p>
                )}
              </div>
            )}
          </div>
        </div>
      </Card>
    </>
  )
}
