/**
 * Investments — holdings and allocation from your brokerage connections.
 *
 * Return is reported only across positions that actually have a cost basis, and
 * the count of those that don't is shown. Plaid does not always supply a basis,
 * and quietly treating a missing one as zero would report a fictional gain.
 */

import { CompositionBar, RankedBars } from '../components/charts'
import {
  Badge, Card, CardHeader, DataTable, Delta, EmptyState, ErrorState, Hero, LegendKey,
  Loading, SectionTitle, StatTile, money, moneyCompact,
} from '../components/ui'
import { useAsync } from '../hooks/useAsync'
import { api, type Holding } from '../lib/api'
import { mediumDate, pct } from '../lib/format'

interface Portfolio {
  holdings: Holding[]
  total_value: number
  allocation: { type: string; value: number; weight: number }[]
  cost_basis: number
  total_gain: number | null
  total_gain_pct: number | null
  positions_missing_basis: number
  accounts: { id: number; name: string; institution: string; balance_current: number; last_synced: string | null }[]
}

export default function Investments({ version }: { version: number }) {
  const { data, error, loading, reload, refreshing } = useAsync<Portfolio>(
    () => api.investments(), [version],
  )

  if (loading) return <Loading label="Loading portfolio" />
  if (error) return <ErrorState message={error} onRetry={reload} />
  if (!data) return null

  if (!data.holdings.length) {
    return (
      <Card>
        <EmptyState title="No holdings yet">
          Connect a brokerage from the Accounts tab — through SnapTrade, which reaches Robinhood
          and most others, or Plaid's investments product. Both return holdings and cost basis
          over the brokerage's own login, so your password never passes through this app.
        </EmptyState>
      </Card>
    )
  }

  const gainers = data.holdings.filter((h) => h.gain !== null && h.gain > 0)
  const losers = data.holdings.filter((h) => h.gain !== null && h.gain < 0)

  return (
    <div className={refreshing ? 'opacity-70 transition-opacity' : undefined}>
      <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_minmax(0,2fr)]">
        <Card>
          <Hero
            label="Portfolio value"
            value={money(data.total_value, false)}
            delta={data.total_gain_pct}
            deltaLabel="against cost basis"
            footnote={
              data.total_gain !== null
                ? `${money(data.total_gain, false)} unrealised across ${data.holdings.length - data.positions_missing_basis} priced positions`
                : 'No cost basis reported, so return cannot be calculated.'
            }
          />
        </Card>

        <div className="grid gap-3 sm:grid-cols-2">
          <StatTile
            label="Cost basis"
            value={money(data.cost_basis, false)}
            sub={
              data.positions_missing_basis
                ? `${data.positions_missing_basis} position(s) report no basis and are excluded`
                : 'Across every position'
            }
          />
          <StatTile label="Positions" value={String(data.holdings.length)} />
          <StatTile
            label="Up"
            value={String(gainers.length)}
            sub={gainers.length ? `best ${gainers[0]?.symbol ?? gainers[0]?.name}` : undefined}
          />
          <StatTile
            label="Down"
            value={String(losers.length)}
            sub={losers.length ? `worst ${losers[losers.length - 1]?.symbol ?? ''}` : undefined}
          />
        </div>
      </div>

      <SectionTitle>Allocation</SectionTitle>
      <Card>
        <CardHeader title="By security type" subtitle="Share of total portfolio value" />
        <CompositionBar
          parts={data.allocation.map((a) => ({ label: a.type, value: a.value }))}
          total={data.total_value}
        />
        <div className="mt-1">
          <LegendKey
            items={data.allocation.map((a, i) => ({
              label: `${a.type} ${pct(a.weight, 1)}`,
              colorIndex: i % 8,
              value: moneyCompact(a.value),
            }))}
          />
        </div>
      </Card>

      <div className="mt-4 grid gap-4 lg:grid-cols-2">
        <Card>
          <CardHeader title="Largest positions" subtitle="By current market value" />
          <RankedBars
            items={data.holdings.map((h) => ({
              label: h.symbol || h.name,
              value: h.value,
              sublabel: `${h.name} · ${pct(h.weight, 1)} of portfolio`,
            }))}
            maxBars={10}
            colorIndex={2}
          />
        </Card>

        <Card>
          <CardHeader title="Accounts" subtitle="Brokerage accounts feeding this view" />
          <DataTable
            columns={[
              {
                key: 'name',
                header: 'Account',
                render: (a) => (
                  <div>
                    <div className="font-medium text-[var(--text-primary)]">{a.name}</div>
                    <div className="text-xs text-[var(--text-muted)]">{a.institution}</div>
                  </div>
                ),
              },
              {
                key: 'synced',
                header: 'Last synced',
                align: 'right',
                render: (a) => (
                  <span className="text-xs text-[var(--text-muted)]">
                    {a.last_synced ? mediumDate(a.last_synced.slice(0, 10)) : 'never'}
                  </span>
                ),
              },
              {
                key: 'value',
                header: 'Value',
                align: 'right',
                numeric: true,
                render: (a) => <span className="font-semibold">{money(a.balance_current)}</span>,
              },
            ]}
            rows={data.accounts}
            rowKey={(a) => a.id}
          />
        </Card>
      </div>

      <SectionTitle>Every holding</SectionTitle>
      <Card>
        <DataTable
          dense
          columns={[
            {
              key: 'symbol',
              header: 'Position',
              render: (h: Holding) => (
                <div>
                  <div className="flex items-center gap-1.5">
                    <span className="font-semibold text-[var(--text-primary)]">
                      {h.symbol || '—'}
                    </span>
                    {h.security_type && (
                      <Badge tone="neutral" icon={false}>
                        {h.security_type.replace(/_/g, ' ')}
                      </Badge>
                    )}
                  </div>
                  <div className="text-xs text-[var(--text-muted)]">{h.name}</div>
                </div>
              ),
            },
            { key: 'quantity', header: 'Shares', align: 'right', numeric: true,
              render: (h) => (
                <span className="text-[var(--text-secondary)]">
                  {h.quantity.toLocaleString(undefined, { maximumFractionDigits: 6 })}
                </span>) },
            { key: 'price', header: 'Price', align: 'right', numeric: true,
              render: (h) => <span className="text-[var(--text-secondary)]">{money(h.price)}</span> },
            { key: 'basis', header: 'Cost basis', align: 'right', numeric: true,
              render: (h) => (
                <span className="text-[var(--text-muted)]">
                  {h.cost_basis !== null ? money(h.cost_basis) : 'not reported'}
                </span>) },
            { key: 'gain', header: 'Gain', align: 'right', numeric: true,
              render: (h) =>
                h.gain !== null && h.gain_pct !== null ? (
                  <div className="whitespace-nowrap">
                    <div className="font-medium"
                         style={{ color: h.gain >= 0 ? 'var(--success-text)' : 'var(--danger-text)' }}>
                      {money(h.gain)}
                    </div>
                    <Delta value={h.gain_pct} />
                  </div>
                ) : <span className="text-xs text-[var(--text-muted)]">—</span> },
            { key: 'weight', header: 'Weight', align: 'right', numeric: true,
              render: (h) => (
                <span className="text-[var(--text-secondary)]">{pct(h.weight, 1)}</span>) },
            { key: 'value', header: 'Value', align: 'right', numeric: true,
              render: (h) => <span className="font-semibold">{money(h.value)}</span> },
          ]}
          rows={data.holdings}
          rowKey={(h) => h.id}
          footer={
            <tr>
              <td className="pt-2 text-xs font-semibold text-[var(--text-secondary)]">Total</td>
              <td colSpan={5} />
              <td className="tnum pt-2 text-right font-semibold">{money(data.total_value)}</td>
            </tr>
          }
        />
        <p className="mt-3 text-xs text-[var(--text-muted)]">
          Prices are whatever the provider last reported, not a live quote — this is a position
          tracker, not a trading screen. Money moved into the brokerage is categorised as a
          transfer, so funding the account never shows up as spending.
        </p>
      </Card>
    </div>
  )
}
