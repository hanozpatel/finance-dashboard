/**
 * Accounts — linking, importing, and the categorisation rules.
 *
 * Three routes, and each says why it exists, because "why not one provider for
 * everything" is the first question this screen raises:
 *
 *  - Plaid covers banks and credit cards.
 *  - SnapTrade covers brokerages — Robinhood above all, which publishes no API
 *    of its own and often will not link through Plaid. Its flow is shaped
 *    differently: the login happens on SnapTrade's own page and nothing is
 *    handed back, so finishing is a second, explicit step.
 *  - CSV covers what no aggregator can reach — Apple Card and Apple Savings,
 *    which Apple permits *no* third party to read. A hard limit, not a gap.
 *
 * When a provider is not configured, the reason is shown rather than the button
 * being disabled — "PLAID_SECRET is not set" is actionable; a greyed button is
 * not.
 */

import {
  CloudOff, FileUp, Link2, Plus, RefreshCw, Trash2, Unplug, Upload,
} from 'lucide-react'
import { useState } from 'react'

import {
  Badge, Banner, Button, Card, CardHeader, DataTable, EmptyState, ErrorState, Field,
  Loading, NumberInput, SectionTitle, Select, TextInput, money,
} from '../components/ui'
import { useAsync } from '../hooks/useAsync'
import { api, errorMessage, type Account, type Connection, type PlaidLinkKind } from '../lib/api'
import { mediumDate, relativeDays, todayISO } from '../lib/format'
import { BROWSER_APP, INSTALL_URL, deleteAllData, downloadBackup, restoreBackup } from '../lib/runtime'

declare global {
  interface Window {
    Plaid?: {
      create: (config: Record<string, unknown>) => { open: () => void }
    }
  }
}

/** Load a provider SDK once, on demand. */
function loadScript(src: string): Promise<void> {
  return new Promise((resolve, reject) => {
    const existing = document.querySelector<HTMLScriptElement>(`script[src="${src}"]`)
    if (existing) {
      if (existing.dataset.loaded === 'true') resolve()
      else {
        existing.addEventListener('load', () => resolve())
        existing.addEventListener('error', () => reject(new Error(`Could not load ${src}`)))
      }
      return
    }
    const script = document.createElement('script')
    script.src = src
    script.async = true
    script.onload = () => { script.dataset.loaded = 'true'; resolve() }
    script.onerror = () => reject(new Error(`Could not load ${src}. Check your connection.`))
    document.head.appendChild(script)
  })
}

export default function Accounts({
  version, onChanged,
}: { version: number; onChanged: () => void }) {
  const [busy, setBusy] = useState<string | null>(null)
  const [note, setNote] = useState<{ tone: 'good' | 'critical'; text: string } | null>(null)
  const [localVersion, setLocalVersion] = useState(0)

  const connections = useAsync(() => api.connections(), [version, localVersion])
  const accounts = useAsync(() => api.accounts(), [version, localVersion])

  function refresh() {
    setLocalVersion((v) => v + 1)
    onChanged()
  }

  /** Open Plaid Link for one kind of institution and store what comes back. */
  async function launchPlaid(kind: PlaidLinkKind) {
    setBusy(kind)
    try {
      const linkToken = await api.plaidLinkToken(kind)
      await loadScript('https://cdn.plaid.com/link/v2/stable/link-initialize.js')
      if (!window.Plaid) throw new Error('Plaid Link did not initialise.')
      const handler = window.Plaid.create({
        token: linkToken,
        onSuccess: async (publicToken: string, metadata: { institution?: { name?: string } }) => {
          try {
            const result = await api.connectPlaid({
              public_token: publicToken,
              institution: metadata.institution?.name,
              kind,
            })
            // A bank link is measured in transactions, a brokerage link in
            // positions, so report whichever one this link actually produced.
            const detail = kind === 'investments'
              ? `${result.holdings} holdings`
              : `${result.inserted} transactions imported`
            setNote({
              tone: 'good',
              text: result.note
                ? `Linked ${result.institution}: ${result.accounts} account(s). ${result.note}`
                : `Linked ${result.institution}: ${result.accounts} account(s), ${detail}.`,
            })
            refresh()
          } catch (e) {
            setNote({ tone: 'critical', text: errorMessage(e) })
          }
        },
        onExit: () => setBusy(null),
      })
      handler.open()
    } catch (e) {
      setNote({ tone: 'critical', text: errorMessage(e) })
    } finally {
      setBusy(null)
    }
  }

  /** Open SnapTrade's connection portal, then adopt whatever came of it. */
  async function launchSnapTrade() {
    setBusy('snaptrade')
    try {
      const url = await api.snaptradePortal()
      const portal = window.open(url, 'snaptrade', 'width=520,height=760')
      if (!portal) {
        setNote({
          tone: 'critical',
          text: 'Your browser blocked the SnapTrade window. Allow pop-ups for localhost and try again.',
        })
        return
      }
      setNote({
        tone: 'good',
        text: 'Finish logging in to your brokerage in the SnapTrade window. This page picks the accounts up when you are done.',
      })
      // SnapTrade redirects to its own page and tells us nothing, so the only
      // signal available is the window closing.
      const watch = setInterval(() => {
        if (portal.closed) {
          clearInterval(watch)
          void importSnapTrade()
        }
      }, 1000)
    } catch (e) {
      setNote({ tone: 'critical', text: errorMessage(e) })
    } finally {
      setBusy(null)
    }
  }

  async function importSnapTrade() {
    setBusy('snaptrade-import')
    try {
      const result = await api.snaptradeImport()
      setNote(
        result.found === 0
          ? { tone: 'critical', text: 'SnapTrade has no connected brokerage yet. Connect one first.' }
          : {
              tone: 'good',
              text: `Linked ${result.accounts} account(s) with ${result.holdings} holdings.`,
            },
      )
      refresh()
    } catch (e) {
      setNote({ tone: 'critical', text: errorMessage(e) })
    } finally {
      setBusy(null)
    }
  }

  if (connections.loading || accounts.loading) return <Loading label="Loading accounts" />
  if (connections.error) return <ErrorState message={connections.error} onRetry={connections.reload} />
  if (!connections.data || !accounts.data) return null

  const providers = connections.data.providers
  const live = connections.data.connections.filter((c) => c.status !== 'disconnected')

  return (
    <div>
      {note && (
        <div className="mb-4">
          <Banner tone={note.tone} onDismiss={() => setNote(null)}>{note.text}</Banner>
        </div>
      )}

      {!BROWSER_APP && providers.encryption.warning && (
        <div className="mb-4">
          <Banner tone="warning" title="Set an encryption key">
            {providers.encryption.warning}
          </Banner>
        </div>
      )}

      <SectionTitle hint={BROWSER_APP
        ? 'Import the CSV export from each bank, or add accounts by hand. Everything stays in this browser.'
        : 'Plaid reaches most US banks and cards, SnapTrade reaches brokerages, and anything else imports from CSV or is kept by hand.'}>
        Connect an institution
      </SectionTitle>
      <div className="grid gap-4 lg:grid-cols-3">
        {BROWSER_APP ? (
          <Card className="flex flex-col lg:col-span-2">
            <CardHeader
              title="Automatic bank sync"
              subtitle="Available when you install the app on your computer"
            />
            <p className="flex-1 text-xs leading-relaxed text-[var(--text-secondary)]">
              Banks and brokerages only hand transactions to a server holding secret API keys —
              Plaid refuses requests made from a browser at all — and this version has no server:
              it runs entirely on your device. So here, your real data comes in as the CSV export
              every bank offers (import it on the right), or as accounts you add by hand below.
              Installing the app on your own computer adds automatic sync through Plaid and
              SnapTrade, with free keys you get yourself.
            </p>
            <div className="mt-3">
              <a
                href={INSTALL_URL}
                target="_blank"
                rel="noreferrer"
                className="inline-flex items-center gap-1.5 rounded-lg border px-3 py-1.5 text-sm font-medium text-[var(--text-primary)]"
                style={{ borderColor: 'var(--border-strong)' }}
              >
                <Link2 size={14} />
                How to install it
              </a>
            </div>
          </Card>
        ) : (
          <>
        <ProviderCard
          name="Plaid · banks and cards"
          purpose="Checking · savings · credit cards"
          configured={providers.plaid.configured}
          problem={providers.plaid.problem}
          environment={providers.plaid.environment}
          setup={
            <>
              Set <Code>PLAID_CLIENT_ID</Code> and <Code>PLAID_SECRET</Code> in{' '}
              <Code>backend/.env</Code>. This link requests only the <Code>transactions</Code>{' '}
              product and asks for two years of history. Link each institution separately — every
              bank is its own login.
            </>
          }
          action={
            <Button
              variant="primary"
              onClick={() => launchPlaid('bank')}
              disabled={!providers.plaid.configured || busy === 'bank'}
            >
              <Link2 size={14} />
              {busy === 'bank' ? 'Opening…' : 'Link a bank or card'}
            </Button>
          }
        />

        <ProviderCard
          name="SnapTrade · brokerage"
          purpose="Robinhood, Fidelity, Schwab, and other brokerages"
          configured={providers.snaptrade.configured}
          problem={providers.snaptrade.problem}
          setup={
            <>
              Brokerages go through SnapTrade, which specialises in them — including Robinhood,
              which publishes no API of its own and often will not link through Plaid. Set{' '}
              <Code>SNAPTRADE_CLIENT_ID</Code> and <Code>SNAPTRADE_CONSUMER_KEY</Code> in{' '}
              <Code>backend/.env</Code> — the Personal tier is free and needs no business
              registration. The login happens on SnapTrade's page, read-only; trading is never
              requested.
            </>
          }
          action={
            <div className="flex flex-wrap gap-2">
              <Button
                variant="primary"
                onClick={launchSnapTrade}
                disabled={!providers.snaptrade.configured || busy === 'snaptrade'}
              >
                <Link2 size={14} />
                {busy === 'snaptrade' ? 'Opening…' : 'Connect a brokerage'}
              </Button>
              {/* Nothing is handed back from SnapTrade's page, so finishing is
                  explicit — and safe to press twice. */}
              <Button
                onClick={importSnapTrade}
                disabled={!providers.snaptrade.configured || busy === 'snaptrade-import'}
              >
                <RefreshCw size={14} />
                {busy === 'snaptrade-import' ? 'Importing…' : 'Finish linking'}
              </Button>
            </div>
          }
        />

          </>
        )}

        <ProviderCard
          name="CSV import"
          purpose="Apple Savings · Apple Card · anything else"
          configured
          problem={null}
          setup={
            <>
              Apple permits <strong>no</strong> third-party aggregation — not Plaid, not anyone —
              so this is the only route to Apple data, and it is a supported path rather than a
              fallback. In Wallet: open the card, tap Card Balance, pick a month, then Export
              Transactions. Apple Savings issues PDF statements only, so keep it as a manual account
              and update the balance when you check it.
            </>
          }
          action={null}
        />
      </div>

      {BROWSER_APP && <YourData />}

      {live.length > 0 && (
        <>
          <SectionTitle>Linked connections</SectionTitle>
          <Card>
            <DataTable
              columns={[
                {
                  key: 'institution',
                  header: 'Institution',
                  render: (c: Connection) => (
                    <div>
                      <div className="font-medium text-[var(--text-primary)]">
                        {c.institution ?? 'Unknown'}
                      </div>
                      <div className="text-xs capitalize text-[var(--text-muted)]">
                        via {c.provider} · {c.account_count} account(s)
                      </div>
                    </div>
                  ),
                },
                {
                  key: 'status',
                  header: 'Status',
                  render: (c: Connection) =>
                    c.status === 'active'
                      ? <Badge tone="good">Active</Badge>
                      : <Badge tone="critical">Error</Badge>,
                },
                {
                  key: 'error',
                  header: '',
                  render: (c: Connection) =>
                    c.error
                      ? <span className="text-xs text-[var(--danger-text)]">{c.error}</span>
                      : null,
                },
                {
                  key: 'synced',
                  header: 'Last synced',
                  align: 'right',
                  render: (c: Connection) => (
                    <span className="whitespace-nowrap text-xs text-[var(--text-muted)]">
                      {c.last_synced ? relativeDays(c.last_synced.slice(0, 10)) : 'never'}
                    </span>
                  ),
                },
                {
                  key: 'actions',
                  header: '',
                  align: 'right',
                  render: (c: Connection) => (
                    <div className="flex justify-end gap-1.5">
                      <Button
                        size="sm"
                        onClick={async () => {
                          setBusy(`sync-${c.id}`)
                          try {
                            await api.syncOne(c.id)
                            setNote({ tone: 'good', text: `Synced ${c.institution}.` })
                            refresh()
                          } catch (e) {
                            setNote({ tone: 'critical', text: errorMessage(e) })
                          } finally {
                            setBusy(null)
                          }
                        }}
                        disabled={busy === `sync-${c.id}`}
                      >
                        <RefreshCw size={12} className={busy === `sync-${c.id}` ? 'animate-spin' : undefined} />
                        Sync
                      </Button>
                      <Button
                        size="sm"
                        variant="ghost"
                        onClick={async () => {
                          if (!window.confirm(
                            `Disconnect ${c.institution}?\n\nThe stored access token is destroyed. The accounts and their transaction history are kept — they simply stop updating.`,
                          )) return
                          try {
                            await api.disconnect(c.id, false)
                            setNote({ tone: 'good', text: `Disconnected ${c.institution}.` })
                            refresh()
                          } catch (e) {
                            setNote({ tone: 'critical', text: errorMessage(e) })
                          }
                        }}
                      >
                        <Unplug size={12} /> Disconnect
                      </Button>
                    </div>
                  ),
                },
              ]}
              rows={live}
              rowKey={(c) => c.id}
            />
          </Card>
        </>
      )}

      <SectionTitle hint="Manual accounts carry their balance into net worth exactly like synced ones.">
        Accounts
      </SectionTitle>
      <Card>
        <DataTable
          columns={[
            {
              key: 'name',
              header: 'Account',
              render: (a: Account) => (
                <div>
                  <div className="flex items-center gap-1.5">
                    <span className="font-medium text-[var(--text-primary)]">{a.name}</span>
                    {a.provider === 'manual' && <Badge tone="neutral" icon={false}>manual</Badge>}
                    {a.connection_status === 'error' && <Badge tone="critical">needs relink</Badge>}
                  </div>
                  <div className="text-xs text-[var(--text-muted)]">
                    {a.institution}
                    {a.mask ? ` ···· ${a.mask}` : ''} · {a.subtype?.replace(/_/g, ' ') ?? a.type}
                  </div>
                  {a.notes && (
                    <div className="text-xs italic text-[var(--text-muted)]">{a.notes}</div>
                  )}
                </div>
              ),
            },
            {
              key: 'transactions',
              header: 'Transactions',
              align: 'right',
              numeric: true,
              render: (a: Account) => (
                <div className="whitespace-nowrap text-xs text-[var(--text-muted)]">
                  <div>{(a.transaction_count ?? 0).toLocaleString()}</div>
                  {a.latest_transaction && <div>to {mediumDate(a.latest_transaction)}</div>}
                </div>
              ),
            },
            {
              key: 'apy',
              header: 'APY',
              align: 'right',
              // Only cash accounts earn interest. Offering the field on a card
              // or a brokerage invites a number that means nothing and would
              // then feed the idle-cash comparison.
              render: (a: Account) =>
                a.type === 'depository' ? (
                  <div className="w-24">
                    <NumberInput
                      value={a.apy ?? 0}
                      suffix="%"
                      step={0.05}
                      min={0}
                      onChange={async (v) => {
                        try {
                          await api.updateAccount(a.id, { apy: v })
                          refresh()
                        } catch (e) {
                          setNote({ tone: 'critical', text: errorMessage(e) })
                        }
                      }}
                    />
                  </div>
                ) : (
                  <span className="text-xs text-[var(--text-muted)]">—</span>
                ),
            },
            {
              key: 'balance',
              header: 'Balance',
              align: 'right',
              render: (a: Account) =>
                a.provider === 'manual' ? (
                  <div className="w-32">
                    <NumberInput
                      value={a.balance_current}
                      prefix="$"
                      step={100}
                      onChange={async (v) => {
                        try {
                          await api.updateAccount(a.id, { balance_current: v })
                          refresh()
                        } catch (e) {
                          setNote({ tone: 'critical', text: errorMessage(e) })
                        }
                      }}
                    />
                  </div>
                ) : (
                  <span
                    className="tnum font-semibold"
                    style={{ color: a.balance_current < 0 ? 'var(--danger-text)' : undefined }}
                  >
                    {money(a.balance_current)}
                  </span>
                ),
            },
            {
              key: 'actions',
              header: '',
              align: 'right',
              render: (a: Account) => (
                <Button
                  size="sm"
                  variant="ghost"
                  onClick={async () => {
                    if (!window.confirm(
                      `Delete ${a.name}?\n\nThis removes the account and all ${a.transaction_count ?? 0} of its transactions. Every past month's spending total will change. This cannot be undone.`,
                    )) return
                    try {
                      const result = await api.deleteAccount(a.id)
                      setNote({
                        tone: 'good',
                        text: `Deleted ${result.deleted} and ${result.transactions_removed} transactions.`,
                      })
                      refresh()
                    } catch (e) {
                      setNote({ tone: 'critical', text: errorMessage(e) })
                    }
                  }}
                >
                  <Trash2 size={12} />
                </Button>
              ),
            },
          ]}
          rows={accounts.data.accounts}
          rowKey={(a) => a.id}
          empty="No accounts yet."
          footer={
            <tr>
              <td className="pt-2 text-xs font-semibold text-[var(--text-secondary)]">Net worth</td>
              <td colSpan={2} />
              <td className="tnum pt-2 text-right font-semibold">
                {money(accounts.data.net_worth.net_worth)}
              </td>
              <td />
            </tr>
          }
        />
      </Card>

      <div className="mt-4 grid gap-4 lg:grid-cols-2">
        <ManualAccountForm onCreated={(name) => {
          setNote({ tone: 'good', text: `Created ${name}.` })
          refresh()
        }} onError={(text) => setNote({ tone: 'critical', text })} />

        <CsvImport
          accounts={accounts.data.accounts}
          onImported={(text) => { setNote({ tone: 'good', text }); refresh() }}
          onError={(text) => setNote({ tone: 'critical', text })}
        />

        <ManualTransactionForm
          accounts={accounts.data.accounts}
          onRecorded={(text) => { setNote({ tone: 'good', text }); refresh() }}
          onError={(text) => setNote({ tone: 'critical', text })}
        />
      </div>

      <RulesPanel />
    </div>
  )
}

function Code({ children }: { children: React.ReactNode }) {
  return (
    <code
      className="rounded px-1 py-0.5 text-[0.8em]"
      style={{ background: 'var(--surface-2)', color: 'var(--text-primary)' }}
    >
      {children}
    </code>
  )
}

function ProviderCard({
  name, purpose, configured, problem, environment, setup, action,
}: {
  name: string
  purpose: string
  configured: boolean
  problem: string | null
  environment?: string
  setup: React.ReactNode
  action: React.ReactNode
}) {
  return (
    <Card className="flex flex-col">
      <div className="flex items-start justify-between gap-2">
        <div>
          <h3 className="text-sm font-semibold text-[var(--text-primary)]">{name}</h3>
          <p className="mt-0.5 text-xs text-[var(--text-muted)]">{purpose}</p>
        </div>
        {configured
          ? <Badge tone="good">Ready</Badge>
          : <Badge tone="neutral"><CloudOff size={10} /> Not set up</Badge>}
      </div>

      {environment && configured && (
        <div className="mt-2">
          <Badge tone={environment === 'sandbox' ? 'warning' : 'info'}>{environment}</Badge>
        </div>
      )}

      {problem && (
        <p className="mt-2.5 text-xs" style={{ color: 'var(--danger-text)' }}>{problem}</p>
      )}

      <p className="mt-2.5 flex-1 text-xs leading-relaxed text-[var(--text-secondary)]">{setup}</p>

      {action && <div className="mt-3">{action}</div>}
    </Card>
  )
}

function ManualAccountForm({
  onCreated, onError,
}: { onCreated: (name: string) => void; onError: (text: string) => void }) {
  const [institution, setInstitution] = useState('Apple')
  const [name, setName] = useState('Apple Savings')
  const [type, setType] = useState<'depository' | 'credit' | 'investment'>('depository')
  const [subtype, setSubtype] = useState('savings')
  const [accountNumber, setAccountNumber] = useState('')
  const [balance, setBalance] = useState(0)
  const [apy, setApy] = useState(4.15)
  const [notes, setNotes] = useState('')
  const [saving, setSaving] = useState(false)

  return (
    <Card>
      <CardHeader
        title="Add an account by hand"
        subtitle="For Apple Savings, cash, or anything no provider reaches"
      />
      <div className="grid gap-3 sm:grid-cols-2">
        <Field label="Institution">
          <TextInput value={institution} onChange={setInstitution} />
        </Field>
        <Field label="Account name">
          <TextInput value={name} onChange={setName} />
        </Field>
        <Field label="Type">
          <Select
            value={type}
            onChange={(v) => setType(v as typeof type)}
            options={[
              { value: 'depository', label: 'Cash (checking or savings)' },
              { value: 'credit', label: 'Credit card' },
              { value: 'investment', label: 'Investment' },
            ]}
          />
        </Field>
        <Field label="Subtype">
          <TextInput value={subtype} onChange={setSubtype} />
        </Field>
        <Field
          label="Account number"
          hint="Optional, for your own reference. Stored only in the local database; listings show the last four."
        >
          <TextInput
            value={accountNumber}
            onChange={setAccountNumber}
            placeholder="e.g. 1234567890"
          />
        </Field>
        <Field label="Current balance">
          <NumberInput value={balance} prefix="$" step={100} onChange={setBalance} />
        </Field>
        <Field label="APY" hint="Drives the idle-cash finding and the savings projection.">
          <NumberInput value={apy} suffix="%" step={0.05} min={0} onChange={setApy} />
        </Field>
        <Field label="Notes" hint="Anything you want to remember about this account.">
          <TextInput value={notes} onChange={setNotes} placeholder="Optional" />
        </Field>
      </div>
      <div className="mt-3">
        <Button
          variant="primary"
          size="sm"
          disabled={saving || !name || !institution}
          onClick={async () => {
            setSaving(true)
            try {
              await api.createAccount({
                institution, name, type, subtype,
                account_number: accountNumber || null,
                notes: notes || null,
                balance_current: balance,
                apy: apy || null,
              })
              onCreated(name)
              setAccountNumber('')
              setNotes('')
              setBalance(0)
            } catch (e) {
              onError(errorMessage(e))
            } finally {
              setSaving(false)
            }
          }}
        >
          <Plus size={13} /> Create account
        </Button>
      </div>
      <p className="mt-2 text-xs text-[var(--text-muted)]">
        A credit balance is stored as a negative number, so net worth is a plain sum — enter what
        you owe as a positive figure and it is converted for you. Nothing here is ever sent
        anywhere; the account number is only so you can tell two accounts apart.
      </p>
    </Card>
  )
}

/**
 * Record a transaction against a manual account.
 *
 * Apple Savings pays interest monthly and issues PDF statements only, so the
 * only way that money enters the ledger is by hand. Moving the balance at the
 * same time is the default because the alternative — a ledger that disagrees
 * with the headline balance — is the thing that makes manual accounts feel
 * untrustworthy.
 */
function ManualTransactionForm({
  accounts, onRecorded, onError,
}: {
  accounts: Account[]
  onRecorded: (text: string) => void
  onError: (text: string) => void
}) {
  const manual = accounts.filter((a) => a.provider === 'manual')
  const [accountId, setAccountId] = useState(String(manual[0]?.id ?? ''))
  const [date, setDate] = useState(todayISO())
  const [amount, setAmount] = useState(0)
  const [description, setDescription] = useState('Interest paid')
  const [category, setCategory] = useState('Income')
  const [updateBalance, setUpdateBalance] = useState(true)
  const [saving, setSaving] = useState(false)

  if (!manual.length) {
    return (
      <Card>
        <CardHeader title="Record a transaction" subtitle="For manual accounts" />
        <EmptyState title="No manual accounts yet">
          Create one above — Apple Savings, for instance — and you can log its monthly interest
          here.
        </EmptyState>
      </Card>
    )
  }

  return (
    <Card>
      <CardHeader
        title="Record a transaction"
        subtitle="Interest, a deposit, or a withdrawal on a manual account"
      />
      <div className="grid gap-3 sm:grid-cols-2">
        <Field label="Account">
          <Select
            value={accountId}
            onChange={setAccountId}
            options={manual.map((a) => ({
              value: String(a.id),
              label: `${a.institution} — ${a.name}`,
            }))}
          />
        </Field>
        <Field label="Date">
          <input
            type="date"
            value={date}
            onChange={(e) => setDate(e.target.value)}
            className="w-full rounded-lg border bg-[var(--surface-1)] px-2.5 py-2 text-sm text-[var(--text-primary)] outline-none focus:ring-2"
            style={{ borderColor: 'var(--border)' }}
          />
        </Field>
        <Field label="Description">
          <TextInput value={description} onChange={setDescription} />
        </Field>
        <Field label="Category">
          <Select
            value={category}
            onChange={setCategory}
            options={[
              { value: 'Income', label: 'Income (interest, dividends)' },
              { value: 'Transfer', label: 'Transfer (moving your own money)' },
              { value: 'Uncategorized', label: 'Something else' },
            ]}
          />
        </Field>
        <Field
          label="Amount"
          hint="Positive for money in, negative for money out."
        >
          <NumberInput value={amount} prefix="$" step={10} onChange={setAmount} />
        </Field>
        <div className="flex items-end pb-2">
          <label className="flex items-center gap-2 text-xs text-[var(--text-secondary)]">
            <input
              type="checkbox"
              checked={updateBalance}
              onChange={(e) => setUpdateBalance(e.target.checked)}
            />
            Move the account balance by this amount too
          </label>
        </div>
      </div>
      <div className="mt-3">
        <Button
          variant="primary"
          size="sm"
          disabled={saving || !accountId || !amount || !description}
          onClick={async () => {
            setSaving(true)
            try {
              const result = await api.createTransaction({
                account_id: Number(accountId),
                date,
                amount,
                description,
                category,
                subcategory: category === 'Income' ? 'Interest' : null,
                update_balance: updateBalance,
              })
              onRecorded(
                result.inserted
                  ? `Recorded ${description}.` + (result.balance_updated
                    ? ` Balance is now ${money(result.balance)}.` : '')
                  : 'That transaction was already recorded, so nothing changed.',
              )
              setAmount(0)
            } catch (e) {
              onError(errorMessage(e))
            } finally {
              setSaving(false)
            }
          }}
        >
          <Plus size={13} /> Record it
        </Button>
      </div>
      <p className="mt-2 text-xs text-[var(--text-muted)]">
        Interest is categorised as income, so it lifts your savings rate rather than counting as
        spending. Recording the same amount on the same date twice is recognised and skipped.
      </p>
    </Card>
  )
}

interface Preview {
  upload_token: string
  headers: string[]
  row_count: number
  header_row: number
  delimiter: string
  detected_preset: string | null
  detected_preset_label: string | null
  mapping: Record<string, string>
  sample_parsed: { date: string; amount: number; description: string }[]
  problems: string[]
}

function CsvImport({
  accounts, onImported, onError,
}: {
  accounts: Account[]
  onImported: (text: string) => void
  onError: (text: string) => void
}) {
  const [preview, setPreview] = useState<Preview | null>(null)
  const [accountId, setAccountId] = useState('')
  const [sign, setSign] = useState('negative_is_spend')
  const [busy, setBusy] = useState(false)

  async function choose(file: File) {
    setBusy(true)
    try {
      const result: Preview = await api.importPreview(file)
      setPreview(result)
      setSign(result.mapping.sign ?? 'negative_is_spend')
      // Guess the destination from the detected preset, so the common case is
      // one click.
      const guess = accounts.find((a) =>
        result.detected_preset === 'apple_card' ? a.institution === 'Apple'
          : result.detected_preset === 'chase' ? a.institution === 'Chase'
            : result.detected_preset === 'bofa' ? a.institution.includes('America') : false)
      if (guess) setAccountId(String(guess.id))
    } catch (e) {
      onError(errorMessage(e))
    } finally {
      setBusy(false)
    }
  }

  return (
    <Card>
      <CardHeader
        title="Import a CSV"
        subtitle="The only route to Apple data, and a universal fallback"
      />

      {!preview ? (
        <label
          className="flex cursor-pointer flex-col items-center justify-center gap-2 rounded-lg border border-dashed py-8 text-center transition-colors hover:bg-[var(--surface-2)]"
          style={{ borderColor: 'var(--border-strong)' }}
        >
          <Upload size={20} className="text-[var(--text-muted)]" />
          <span className="text-sm font-medium text-[var(--text-primary)]">
            {busy ? 'Reading…' : 'Choose a CSV file'}
          </span>
          <span className="max-w-xs text-xs text-[var(--text-muted)]">
            Apple Card, Chase, and Bank of America exports are recognised automatically. Anything
            else gets a column mapping you can correct.
          </span>
          <input
            type="file"
            accept=".csv,text/csv"
            className="hidden"
            onChange={(e) => {
              const file = e.target.files?.[0]
              if (file) choose(file)
              e.target.value = ''
            }}
          />
        </label>
      ) : (
        <div>
          <div className="flex flex-wrap items-center gap-2">
            <Badge tone="good">{preview.row_count} rows</Badge>
            {preview.detected_preset_label && (
              <Badge tone="info">{preview.detected_preset_label}</Badge>
            )}
            <button
              onClick={() => setPreview(null)}
              className="ml-auto text-xs text-[var(--text-muted)] hover:text-[var(--text-primary)] hover:underline"
            >
              Start over
            </button>
          </div>

          <div className="mt-3 grid gap-3 sm:grid-cols-2">
            <Field label="Import into">
              <Select
                value={accountId}
                onChange={setAccountId}
                placeholder="Choose an account"
                options={accounts.map((a) => ({
                  value: String(a.id),
                  label: `${a.institution} — ${a.name}`,
                }))}
              />
            </Field>
            <Field
              label="Sign convention"
              hint="Apple signs purchases positive; most banks sign them negative."
            >
              <Select
                value={sign}
                onChange={setSign}
                options={[
                  { value: 'negative_is_spend', label: 'Negative amounts are spending' },
                  { value: 'positive_is_spend', label: 'Positive amounts are spending' },
                ]}
              />
            </Field>
          </div>

          {/* Showing the parsed result is the only reliable way to catch an
              inverted sign before it corrupts a year of analysis. */}
          <div className="mt-3">
            <div className="mb-1.5 text-xs font-semibold text-[var(--text-secondary)]">
              Check these before importing — a purchase must show as a negative amount
            </div>
            <DataTable
              dense
              columns={[
                { key: 'date', header: 'Date', render: (r) => <span className="tnum text-xs">{r.date}</span> },
                { key: 'description', header: 'Description',
                  render: (r) => <span className="text-xs">{r.description}</span> },
                { key: 'amount', header: 'Amount', align: 'right', numeric: true,
                  render: (r) => (
                    <span
                      className="font-semibold"
                      style={{ color: r.amount > 0 ? 'var(--success-text)' : undefined }}
                    >
                      {money(r.amount)}
                    </span>) },
              ]}
              rows={
                sign === preview.mapping.sign
                  ? preview.sample_parsed
                  : preview.sample_parsed.map((r) => ({ ...r, amount: -r.amount }))
              }
              rowKey={(_r, i) => i}
            />
          </div>

          {preview.problems.length > 0 && (
            <div className="mt-3">
              <Banner tone="warning" title={`${preview.problems.length} row(s) could not be read`}>
                {preview.problems.join(' ')}
              </Banner>
            </div>
          )}

          <div className="mt-3">
            <Button
              variant="primary"
              size="sm"
              disabled={!accountId || busy}
              onClick={async () => {
                setBusy(true)
                try {
                  const result = await api.importCommit(Number(accountId), preview.upload_token, {
                    ...preview.mapping,
                    sign,
                    header_row: preview.header_row,
                    delimiter: preview.delimiter,
                  })
                  onImported(
                    `Imported ${result.inserted} transactions from ${result.rows_parsed} rows.`
                    + (result.note ? ` ${result.note}` : ''),
                  )
                  setPreview(null)
                } catch (e) {
                  onError(errorMessage(e))
                } finally {
                  setBusy(false)
                }
              }}
            >
              <FileUp size={13} /> {busy ? 'Importing…' : `Import ${preview.row_count} rows`}
            </Button>
          </div>
          <p className="mt-2 text-xs text-[var(--text-muted)]">
            Safe to re-run on overlapping statements: rows already present are recognised and
            skipped, so importing three months that share two is not a problem.
          </p>
        </div>
      )}
    </Card>
  )
}

function RulesPanel() {
  const [localVersion, setLocalVersion] = useState(0)
  const rules = useAsync(() => api.rules(), [localVersion])
  const cats = useAsync(() => api.categories(), [])
  const [pattern, setPattern] = useState('')
  const [category, setCategory] = useState('')
  const [matchType, setMatchType] = useState('description_contains')
  const [error, setError] = useState<string | null>(null)

  return (
    <>
      <SectionTitle hint="Rules run before every built-in guess, and are reapplied across all history the moment you add one.">
        Categorisation rules
      </SectionTitle>
      <Card>
        {error && (
          <div className="mb-3">
            <Banner tone="critical" onDismiss={() => setError(null)}>{error}</Banner>
          </div>
        )}
        <div className="grid items-end gap-3 sm:grid-cols-[1fr_1fr_1fr_auto]">
          <Field label="When the">
            <Select
              value={matchType}
              onChange={setMatchType}
              options={[
                { value: 'description_contains', label: 'description contains' },
                { value: 'merchant_contains', label: 'merchant contains' },
                { value: 'description_regex', label: 'description matches regex' },
              ]}
            />
          </Field>
          <Field label="This text">
            <TextInput value={pattern} onChange={setPattern} placeholder="e.g. ZEITGEIST" />
          </Field>
          <Field label="Categorize as">
            <Select
              value={category}
              onChange={setCategory}
              placeholder="Choose a category"
              options={(cats.data?.categories ?? []).map((c) => ({ value: c, label: c }))}
            />
          </Field>
          <Button
            variant="primary"
            size="sm"
            disabled={!pattern || !category}
            onClick={async () => {
              try {
                const result = await api.createRule({ match_type: matchType, pattern, category })
                setPattern('')
                setCategory('')
                setLocalVersion((v) => v + 1)
                setError(null)
                if (result.transactions_recategorized === 0) {
                  setError('The rule was saved but matched nothing in your history.')
                }
              } catch (e) {
                setError(errorMessage(e))
              }
            }}
          >
            <Plus size={13} /> Add rule
          </Button>
        </div>

        <div className="mt-4">
          {rules.data?.length ? (
            <DataTable
              dense
              columns={[
                { key: 'match', header: 'Rule',
                  render: (r) => (
                    <span className="text-[var(--text-secondary)]">
                      {r.match_type.replace(/_/g, ' ')} <Code>{r.pattern}</Code>
                    </span>) },
                { key: 'category', header: 'Becomes',
                  render: (r) => (
                    <span className="font-medium">
                      {r.category}
                      {r.subcategory ? ` · ${r.subcategory}` : ''}
                    </span>) },
                { key: 'priority', header: 'Priority', align: 'right', numeric: true,
                  render: (r) => <span className="text-[var(--text-muted)]">{r.priority}</span> },
                {
                  key: 'actions',
                  header: '',
                  align: 'right',
                  render: (r) => (
                    <Button
                      size="sm"
                      variant="ghost"
                      onClick={async () => {
                        try {
                          await api.deleteRule(r.id)
                          setLocalVersion((v) => v + 1)
                        } catch (e) {
                          setError(errorMessage(e))
                        }
                      }}
                    >
                      <Trash2 size={12} />
                    </Button>
                  ),
                },
              ]}
              rows={rules.data}
              rowKey={(r) => r.id}
            />
          ) : (
            <EmptyState title="No rules yet">
              The quickest way to create one is from the Transactions tab: select a few charges,
              recategorise them, and leave “also create a rule” checked.
            </EmptyState>
          )}
        </div>
      </Card>

      <p className="mt-4 text-xs leading-relaxed text-[var(--text-muted)]">
        Everything here stays on this machine. Provider access tokens are encrypted with AES-256-GCM
        before they touch the database, the API binds to localhost only, and there is no telemetry of
        any kind. The APY set on each account feeds the idle-cash finding on the Find Savings tab and
        the down-payment projection on the house tab.
      </p>
    </>
  )
}

/**
 * Web build only. In a browser, the data is as durable as the browser's
 * storage — clearing site data, or a different device, and it is gone — so a
 * copy you can keep, and a clean way to start over, are not optional extras.
 */
function YourData() {
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  return (
    <>
      <SectionTitle hint="Nothing here is ever uploaded. Back it up if it matters to you — clearing this site's data in your browser deletes it.">
        Your data on this device
      </SectionTitle>
      <Card>
        <div className="flex flex-wrap items-center gap-2">
          <Button onClick={() => downloadBackup().catch((e) => setError(errorMessage(e)))}>
            <FileUp size={14} />
            Download a backup
          </Button>
          <label className="inline-flex">
            <input
              type="file"
              accept=".db,.sqlite,application/vnd.sqlite3,application/octet-stream"
              className="sr-only"
              onChange={async (e) => {
                const file = e.target.files?.[0]
                e.target.value = ''
                if (!file) return
                if (!window.confirm('Replace everything in this browser with this backup?')) return
                setBusy(true)
                try { await restoreBackup(file) } catch (err) { setError(errorMessage(err)); setBusy(false) }
              }}
            />
            <span
              className="inline-flex cursor-pointer items-center gap-1.5 rounded-lg border px-3 py-1.5 text-sm font-medium text-[var(--text-primary)]"
              style={{ borderColor: 'var(--border-strong)' }}
            >
              <Upload size={14} />
              {busy ? 'Restoring…' : 'Restore a backup'}
            </span>
          </label>
          <div className="ml-auto">
            <Button
              variant="danger"
              onClick={async () => {
                if (!window.confirm(
                  'Delete every account, transaction, budget and rule from this browser?\n\nThis cannot be undone unless you have a backup.',
                )) return
                try { await deleteAllData() } catch (err) { setError(errorMessage(err)) }
              }}
            >
              <Trash2 size={14} />
              Delete all my data
            </Button>
          </div>
        </div>
        {error && <p className="mt-2 text-xs" style={{ color: 'var(--danger-text)' }}>{error}</p>}
      </Card>
    </>
  )
}
