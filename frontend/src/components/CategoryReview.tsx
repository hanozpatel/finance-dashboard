/**
 * The uncategorised-transaction quiz.
 *
 * Automatic rules handle the merchants a keyword list can recognise and stop at
 * the local restaurant and the ACH bill with a mangled company name. Those are
 * asked rather than guessed, because a wrong category is harder to spot than a
 * missing one.
 *
 * Three things make this worth sitting through rather than abandoning halfway:
 * one question per *merchant* (not per transaction), biggest money first, and
 * every answer stored as a rule so the same question never returns.
 */

import { ArrowRight, Check, Lightbulb, SkipForward, Sparkles, X } from 'lucide-react'
import { useEffect, useMemo, useState } from 'react'

import { Badge, Button, Card, Select, TextInput, money } from './ui'
import { useAsync } from '../hooks/useAsync'
import { api, errorMessage, type ReviewQuestion } from '../lib/api'
import { mediumDate } from '../lib/format'

export default function CategoryReview({
  version, onChanged,
}: { version: number; onChanged: () => void }) {
  const [open, setOpen] = useState(false)
  const [skipped, setSkipped] = useState<Set<string>>(new Set())
  const [localVersion, setLocalVersion] = useState(0)
  const [createRule, setCreateRule] = useState(true)
  const [otherCategory, setOtherCategory] = useState('')
  const [otherSub, setOtherSub] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [caveat, setCaveat] = useState<string | null>(null)

  const queue = useAsync(() => api.reviewQueue(), [version, localVersion])
  const cats = useAsync(() => api.categories(), [])

  // Skipping is a this-session decision, not a stored one: a question you
  // passed over should come back tomorrow, not disappear.
  const pending = useMemo(
    () => (queue.data?.questions ?? []).filter((q) => !skipped.has(q.merchant_key)),
    [queue.data, skipped],
  )
  const current: ReviewQuestion | undefined = pending[0]

  async function answer(category: string, subcategory: string | null) {
    if (!current || busy) return
    setBusy(true)
    setError(null)
    try {
      const result = await api.reviewAnswer({
        merchant_key: current.merchant_key,
        category,
        subcategory,
        create_rule: createRule,
        // A question with no merchant key is a single unnamed row, so it has to
        // be answered by id or the update would match nothing.
        transaction_ids: current.merchant_key.startsWith('txn:')
          ? current.transaction_ids
          : undefined,
      })
      // A rule can be refused as unsafe even though the answer was applied,
      // and silently not remembering it would be the worse surprise.
      setCaveat(result.rule_skipped_reason
        ? `Categorised ${result.updated} transaction${result.updated === 1 ? '' : 's'}, but did not `
          + `save a rule: ${result.rule_skipped_reason}.`
        : null)
      setOtherCategory('')
      setOtherSub('')
      setLocalVersion((v) => v + 1)
      onChanged()
    } catch (e) {
      setError(errorMessage(e))
    } finally {
      setBusy(false)
    }
  }

  function skip() {
    if (current) setSkipped((s) => new Set(s).add(current.merchant_key))
  }

  // Number keys pick a suggestion, S skips. A queue of fifteen is tedious with
  // a mouse and quick from the keyboard.
  useEffect(() => {
    if (!open || !current) return
    function onKey(e: KeyboardEvent) {
      const target = e.target as HTMLElement
      if (target.tagName === 'INPUT' || target.tagName === 'SELECT') return
      const index = Number(e.key) - 1
      if (current && index >= 0 && index < current.suggestions.length) {
        const s = current.suggestions[index]
        void answer(s.category, s.subcategory)
      } else if (e.key.toLowerCase() === 's') {
        skip()
      } else if (e.key === 'Escape') {
        setOpen(false)
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  })

  const stats = queue.data
  if (!stats || stats.remaining === 0) return null

  const answered = stats.remaining - pending.length

  if (!open) {
    return (
      <Card className="mb-4">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div className="flex items-start gap-2.5">
            <Sparkles size={16} className="mt-0.5 shrink-0 text-[var(--accent)]" />
            <div>
              <div className="text-sm font-semibold text-[var(--text-primary)]">
                {stats.transactions} transaction{stats.transactions === 1 ? '' : 's'} still need a
                category
              </div>
              <p className="mt-0.5 text-xs text-[var(--text-muted)]">
                {money(Math.abs(stats.total_amount))} across {stats.remaining} merchant
                {stats.remaining === 1 ? '' : 's'}. Answering once per merchant settles every
                transaction from it, past and future.
              </p>
            </div>
          </div>
          <Button variant="primary" onClick={() => setOpen(true)}>
            <Lightbulb size={14} />
            Review {stats.remaining} merchant{stats.remaining === 1 ? '' : 's'}
          </Button>
        </div>
      </Card>
    )
  }

  if (!current) {
    return (
      <Card className="mb-4">
        <div className="flex items-center justify-between gap-3">
          <div className="flex items-center gap-2 text-sm text-[var(--text-primary)]">
            <Check size={16} style={{ color: 'var(--good-text)' }} />
            {skipped.size > 0
              ? `Done for now — ${skipped.size} skipped, and they will be waiting next time.`
              : 'Everything is categorised.'}
          </div>
          <div className="flex gap-2">
            {skipped.size > 0 && (
              <Button onClick={() => setSkipped(new Set())}>Revisit skipped</Button>
            )}
            <Button onClick={() => setOpen(false)}>Close</Button>
          </div>
        </div>
      </Card>
    )
  }

  const categoryOptions = (cats.data?.categories ?? []).map((c) => ({ value: c, label: c }))

  return (
    <Card className="mb-4">
      <div className="flex items-start justify-between gap-3">
        <div>
          <div className="flex items-center gap-2">
            <span className="text-xs font-medium uppercase tracking-wide text-[var(--text-muted)]">
              {answered + 1} of {stats.remaining}
            </span>
            {current.count > 1 && (
              <Badge tone="info">{current.count} transactions</Badge>
            )}
          </div>
          <h3 className="mt-1 text-lg font-semibold text-[var(--text-primary)]">
            {current.merchant}
          </h3>
          <p className="mt-0.5 text-xs text-[var(--text-muted)]">
            {money(Math.abs(current.total))} · {current.accounts.join(', ')} ·{' '}
            {current.first_date === current.last_date
              ? mediumDate(current.last_date)
              : `${mediumDate(current.first_date)} – ${mediumDate(current.last_date)}`}
          </p>
        </div>
        <button
          onClick={() => setOpen(false)}
          className="rounded p-1 text-[var(--text-muted)] hover:text-[var(--text-primary)]"
          aria-label="Close review"
        >
          <X size={16} />
        </button>
      </div>

      {/* The raw text, because the merchant name is a cleaned-up guess and the
          original is what you would actually recognise or search for. */}
      <div className="mt-3 space-y-1">
        {current.examples.map((e) => (
          <div
            key={e.id}
            className="flex items-baseline justify-between gap-3 rounded border px-2.5 py-1.5 text-xs"
            style={{ borderColor: 'var(--border)' }}
          >
            <span className="truncate font-mono text-[var(--text-secondary)]">{e.description}</span>
            <span className="shrink-0 tabular-nums text-[var(--text-muted)]">
              {mediumDate(e.date)} · {money(e.amount)}
            </span>
          </div>
        ))}
      </div>

      {error && (
        <p className="mt-3 text-xs" style={{ color: 'var(--danger-text)' }}>{error}</p>
      )}
      {caveat && (
        <p className="mt-3 text-xs" style={{ color: 'var(--status-warning)' }}>{caveat}</p>
      )}

      <div className="mt-4 grid gap-2 sm:grid-cols-2">
        {current.suggestions.map((s, i) => (
          <button
            key={`${s.category}-${s.subcategory}`}
            disabled={busy}
            onClick={() => answer(s.category, s.subcategory)}
            className="group flex items-start gap-2.5 rounded-lg border p-2.5 text-left transition disabled:opacity-50"
            style={{ borderColor: 'var(--border)' }}
          >
            <kbd
              className="mt-0.5 shrink-0 rounded border px-1.5 py-0.5 font-mono text-[10px] text-[var(--text-muted)]"
              style={{ borderColor: 'var(--border)' }}
            >
              {i + 1}
            </kbd>
            <span className="min-w-0">
              <span className="block text-sm font-medium text-[var(--text-primary)]">
                {s.category}
                {s.subcategory ? (
                  <span className="text-[var(--text-muted)]"> · {s.subcategory}</span>
                ) : null}
              </span>
              {/* Why it was suggested, so a guess can be judged rather than trusted. */}
              <span className="mt-0.5 block text-xs leading-snug text-[var(--text-muted)]">
                {s.reason}
              </span>
            </span>
          </button>
        ))}
      </div>

      <div className="mt-3 flex flex-wrap items-end gap-2">
        <div className="min-w-[9rem] flex-1">
          <Select
            value={otherCategory}
            onChange={setOtherCategory}
            placeholder="Something else…"
            options={categoryOptions}
          />
        </div>
        <div className="min-w-[9rem] flex-1">
          <TextInput
            value={otherSub}
            onChange={setOtherSub}
            placeholder="Subcategory (optional)"
          />
        </div>
        <Button
          variant="primary"
          disabled={!otherCategory || busy}
          onClick={() => answer(otherCategory, otherSub || null)}
        >
          <ArrowRight size={14} />
          Save
        </Button>
        <Button onClick={skip} disabled={busy}>
          <SkipForward size={14} />
          Skip
        </Button>
      </div>

      <label className="mt-3 flex items-center gap-1.5 text-xs text-[var(--text-secondary)]">
        <input
          type="checkbox"
          checked={createRule}
          onChange={(e) => setCreateRule(e.target.checked)}
        />
        Remember this merchant, so future transactions categorise themselves
      </label>
    </Card>
  )
}
