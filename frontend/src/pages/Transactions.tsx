/**
 * Transactions — the ledger, with the editing the analytics depend on.
 *
 * Recategorising here is what makes every other tab accurate, so the bulk path
 * offers to turn a correction into a standing rule: fixing twelve Zeitgeist
 * charges is useful, but fixing them *and every future one* is the point.
 */

import { ChevronLeft, ChevronRight, Search, Wand2, X } from 'lucide-react'
import { useEffect, useMemo, useState } from 'react'
import { useSearchParams } from 'react-router-dom'

import CategoryReview from '../components/CategoryReview'
import {
  Badge, Banner, Button, Card, DataTable, ErrorState, Loading, NumberInput, Segmented,
  Select, money,
} from '../components/ui'
import { useAsync } from '../hooks/useAsync'
import { api, errorMessage, type Account, type Transaction } from '../lib/api'
import { mediumDate } from '../lib/format'

const PAGE_SIZE = 60

export default function Transactions({ version }: { version: number }) {
  const [params, setParams] = useSearchParams()
  const [search, setSearch] = useState('')
  const [debounced, setDebounced] = useState('')
  const [category, setCategory] = useState('')
  const [accountId, setAccountId] = useState('')
  const [minAmount, setMinAmount] = useState(0)
  const [includeTransfers, setIncludeTransfers] = useState(false)
  const [onlyUncategorized, setOnlyUncategorized] = useState(false)
  const [sort, setSort] = useState<'date' | 'amount'>('date')
  const [page, setPage] = useState(0)
  const [selected, setSelected] = useState<Set<number>>(new Set())
  const [bulkCategory, setBulkCategory] = useState('')
  const [bulkSub, setBulkSub] = useState('')
  const [createRule, setCreateRule] = useState(true)
  const [note, setNote] = useState<string | null>(null)
  const [localVersion, setLocalVersion] = useState(0)

  const merchantKey = params.get('merchant') ?? ''

  // Debounce the search box so typing does not fire a request per keystroke.
  useEffect(() => {
    const id = setTimeout(() => setDebounced(search), 250)
    return () => clearTimeout(id)
  }, [search])

  // Any filter change invalidates the current page offset.
  useEffect(() => {
    setPage(0)
    setSelected(new Set())
  }, [debounced, category, accountId, minAmount, includeTransfers, onlyUncategorized, sort, merchantKey])

  const accounts = useAsync<Account[]>(() => api.accounts().then((r) => r.accounts), [version])
  const cats = useAsync(() => api.categories(), [])

  const query = useMemo(() => ({
    search: debounced || undefined,
    category: category || undefined,
    account_id: accountId || undefined,
    merchant_key: merchantKey || undefined,
    min_amount: minAmount > 0 ? minAmount : undefined,
    include_transfers: includeTransfers,
    uncategorized_only: onlyUncategorized,
    sort,
    direction: 'desc',
    limit: PAGE_SIZE,
    offset: page * PAGE_SIZE,
  }), [debounced, category, accountId, merchantKey, minAmount, includeTransfers,
       onlyUncategorized, sort, page])

  const { data, error, loading, reload, refreshing } = useAsync(
    () => api.transactions(query), [query, version, localVersion],
  )

  async function applyBulk() {
    if (!bulkCategory || !selected.size) return
    try {
      const result = await api.bulkCategorize({
        transaction_ids: [...selected],
        category: bulkCategory,
        subcategory: bulkSub || null,
        create_rule: createRule,
      })
      setNote(
        result.rule_created
          ? `Updated ${result.updated} transactions and created a rule for “${result.rule_created}”, which now applies to future imports too.`
          : `Updated ${result.updated} transactions. ${result.rule_skipped_reason ?? ''}`.trim(),
      )
      setSelected(new Set())
      setBulkCategory('')
      setBulkSub('')
      setLocalVersion((v) => v + 1)
    } catch (e) {
      setNote(errorMessage(e))
    }
  }

  async function toggleExcluded(t: Transaction) {
    try {
      await api.updateTransaction(t.id, { excluded: !t.excluded })
      setLocalVersion((v) => v + 1)
    } catch (e) {
      setNote(errorMessage(e))
    }
  }

  if (loading) return <Loading label="Loading transactions" />
  if (error) return <ErrorState message={error} onRetry={reload} />
  if (!data) return null

  const totalPages = Math.ceil(data.total_count / PAGE_SIZE)
  const allOnPageSelected = data.transactions.length > 0
    && data.transactions.every((t) => selected.has(t.id))

  const categoryOptions = (cats.data?.categories ?? []).map((c) => ({ value: c, label: c }))
  const subOptions = bulkCategory
    ? (cats.data?.subcategories[bulkCategory] ?? []).map((s) => ({ value: s, label: s }))
    : []

  return (
    <div>
      {/* Above the filters, because an uncategorised backlog distorts every
          other tab and is worth clearing before reading any of them. */}
      <CategoryReview version={version + localVersion} onChanged={() => setLocalVersion((v) => v + 1)} />

      {/* One filter row above the table it scopes. */}
      <Card className="mb-4">
        <div className="grid gap-3 md:grid-cols-2 lg:grid-cols-4">
          <div className="relative">
            <Search
              size={14}
              className="pointer-events-none absolute left-2.5 top-1/2 -translate-y-1/2 text-[var(--text-muted)]"
            />
            <input
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="Search description, merchant, or note"
              className="w-full rounded-lg border bg-[var(--surface-1)] py-2 pl-8 pr-2.5 text-sm outline-none placeholder:text-[var(--text-muted)] focus:ring-2"
              style={{ borderColor: 'var(--border)' }}
            />
          </div>
          <Select
            value={category}
            onChange={setCategory}
            placeholder="All categories"
            options={categoryOptions}
          />
          <Select
            value={accountId}
            onChange={setAccountId}
            placeholder="All accounts"
            options={(accounts.data ?? []).map((a) => ({
              value: String(a.id),
              label: `${a.institution} — ${a.name}`,
            }))}
          />
          <NumberInput value={minAmount} onChange={setMinAmount} prefix="$" step={25} min={0} />
        </div>

        <div className="mt-3 flex flex-wrap items-center gap-3">
          <label className="flex items-center gap-1.5 text-xs text-[var(--text-secondary)]">
            <input
              type="checkbox"
              checked={includeTransfers}
              onChange={(e) => setIncludeTransfers(e.target.checked)}
            />
            Include transfers
          </label>
          <label className="flex items-center gap-1.5 text-xs text-[var(--text-secondary)]">
            <input
              type="checkbox"
              checked={onlyUncategorized}
              onChange={(e) => setOnlyUncategorized(e.target.checked)}
            />
            Uncategorized only
          </label>
          <Segmented
            size="sm"
            value={sort}
            onChange={setSort}
            options={[{ value: 'date', label: 'Newest' }, { value: 'amount', label: 'Largest' }]}
          />
          {merchantKey && (
            <Button
              size="sm"
              variant="ghost"
              onClick={() => {
                params.delete('merchant')
                setParams(params)
              }}
            >
              <X size={12} /> merchant: {merchantKey}
            </Button>
          )}
          <span className="ml-auto text-xs text-[var(--text-muted)]">
            <span className="tnum font-semibold text-[var(--text-primary)]">
              {data.total_count.toLocaleString()}
            </span>{' '}
            matching ·{' '}
            <span className="tnum">{money(data.outflow, false)} out</span> ·{' '}
            <span className="tnum">{money(data.inflow, false)} in</span>
          </span>
        </div>
      </Card>

      {note && (
        <div className="mb-4">
          <Banner tone="good" onDismiss={() => setNote(null)}>{note}</Banner>
        </div>
      )}

      {selected.size > 0 && (
        <Card className="mb-4">
          <div className="flex flex-wrap items-end gap-3">
            <span className="text-sm font-medium">
              {selected.size} selected
            </span>
            <div className="w-44">
              <Select
                value={bulkCategory}
                onChange={(v) => { setBulkCategory(v); setBulkSub('') }}
                placeholder="Recategorize to…"
                options={categoryOptions}
              />
            </div>
            {subOptions.length > 0 && (
              <div className="w-44">
                <Select
                  value={bulkSub}
                  onChange={setBulkSub}
                  placeholder="Subcategory (optional)"
                  options={subOptions}
                />
              </div>
            )}
            <label className="flex items-center gap-1.5 text-xs text-[var(--text-secondary)]">
              <input
                type="checkbox"
                checked={createRule}
                onChange={(e) => setCreateRule(e.target.checked)}
              />
              Also create a rule, so future charges land here automatically
            </label>
            <Button variant="primary" size="sm" onClick={applyBulk} disabled={!bulkCategory}>
              <Wand2 size={13} /> Apply
            </Button>
            <Button variant="ghost" size="sm" onClick={() => setSelected(new Set())}>
              Clear
            </Button>
          </div>
        </Card>
      )}

      <Card className={refreshing ? 'opacity-70 transition-opacity' : undefined}>
        <DataTable
          dense
          columns={[
            {
              key: 'select',
              header: '',
              width: '28px',
              render: (t: Transaction) => (
                <input
                  type="checkbox"
                  checked={selected.has(t.id)}
                  onChange={(e) => {
                    const next = new Set(selected)
                    if (e.target.checked) next.add(t.id)
                    else next.delete(t.id)
                    setSelected(next)
                  }}
                  aria-label={`Select ${t.description}`}
                />
              ),
            },
            {
              key: 'date',
              header: 'Date',
              width: '110px',
              render: (t: Transaction) => (
                <span className="tnum whitespace-nowrap text-xs text-[var(--text-secondary)]">
                  {mediumDate(t.date)}
                </span>
              ),
            },
            {
              key: 'description',
              header: 'Merchant',
              render: (t: Transaction) => (
                <div className="min-w-0">
                  <div className="flex items-center gap-1.5">
                    <span
                      className={
                        t.excluded
                          ? 'font-medium text-[var(--text-muted)] line-through'
                          : 'font-medium text-[var(--text-primary)]'
                      }
                    >
                      {t.merchant || t.description}
                    </span>
                    {t.pending ? <Badge tone="neutral" icon={false}>pending</Badge> : null}
                    {t.recurring_name ? (
                      <Badge tone="info" icon={false}>{t.recurring_cadence}</Badge>
                    ) : null}
                  </div>
                  <div className="truncate text-xs text-[var(--text-muted)]" title={t.description}>
                    {t.description}
                  </div>
                  {t.notes && (
                    <div className="text-xs italic text-[var(--text-muted)]">{t.notes}</div>
                  )}
                </div>
              ),
            },
            {
              key: 'category',
              header: 'Category',
              render: (t: Transaction) => (
                <div className="whitespace-nowrap">
                  {t.category === 'Uncategorized' ? (
                    <Badge tone="warning">Uncategorized</Badge>
                  ) : (
                    <span className="text-xs text-[var(--text-secondary)]">{t.category}</span>
                  )}
                  {t.subcategory && (
                    <span className="ml-1 text-xs text-[var(--text-muted)]">· {t.subcategory}</span>
                  )}
                </div>
              ),
            },
            {
              key: 'account',
              header: 'Account',
              render: (t: Transaction) => (
                <span className="whitespace-nowrap text-xs text-[var(--text-muted)]">
                  {t.institution}
                  {t.mask ? ` ··${t.mask}` : ''}
                </span>
              ),
            },
            {
              key: 'amount',
              header: 'Amount',
              align: 'right',
              numeric: true,
              render: (t: Transaction) => (
                <span
                  className="whitespace-nowrap font-semibold"
                  style={{ color: t.amount > 0 ? 'var(--success-text)' : undefined }}
                >
                  {money(t.amount)}
                </span>
              ),
            },
            {
              key: 'actions',
              header: '',
              align: 'right',
              render: (t: Transaction) => (
                <button
                  onClick={() => toggleExcluded(t)}
                  className="whitespace-nowrap text-xs text-[var(--text-muted)] hover:text-[var(--text-primary)] hover:underline"
                  title="Excluded transactions are left out of every spending total"
                >
                  {t.excluded ? 'include' : 'exclude'}
                </button>
              ),
            },
          ]}
          rows={data.transactions}
          rowKey={(t) => t.id}
          empty="No transactions match these filters."
          footer={
            data.transactions.length > 0 ? (
              <tr>
                <td colSpan={7} className="pt-2">
                  <label className="flex items-center gap-1.5 text-xs text-[var(--text-muted)]">
                    <input
                      type="checkbox"
                      checked={allOnPageSelected}
                      onChange={(e) => {
                        const next = new Set(selected)
                        data.transactions.forEach((t) =>
                          e.target.checked ? next.add(t.id) : next.delete(t.id))
                        setSelected(next)
                      }}
                    />
                    Select all {data.transactions.length} on this page
                  </label>
                </td>
              </tr>
            ) : undefined
          }
        />

        {totalPages > 1 && (
          <div className="mt-3 flex items-center justify-between">
            <span className="tnum text-xs text-[var(--text-muted)]">
              Page {page + 1} of {totalPages}
            </span>
            <div className="flex gap-2">
              <Button size="sm" disabled={page === 0} onClick={() => setPage((p) => p - 1)}>
                <ChevronLeft size={13} /> Previous
              </Button>
              <Button size="sm" disabled={!data.has_more} onClick={() => setPage((p) => p + 1)}>
                Next <ChevronRight size={13} />
              </Button>
            </div>
          </div>
        )}
      </Card>

      <p className="mt-3 text-xs text-[var(--text-muted)]">
        Excluding a transaction leaves it in the ledger but out of every spending total — the right
        move for a work expense you were reimbursed for. Transfers are hidden by default because
        they move money between your own accounts rather than spending it.
      </p>
    </div>
  )
}
