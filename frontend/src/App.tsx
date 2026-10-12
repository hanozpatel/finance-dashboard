/**
 * Tab shell.
 *
 * Each tab is a route so it is linkable and the browser's back button works.
 * The header carries net worth and the sync control, because those are true
 * across every tab and repeating them per-page would let them disagree.
 */

import clsx from 'clsx'
import {
  Banknote, CreditCard, Home, LineChart, Monitor, Moon, PiggyBank, RefreshCw,
  Scissors, Sun, Target, Wallet,
} from 'lucide-react'
import { useState } from 'react'
import { NavLink, Navigate, Route, Routes } from 'react-router-dom'

import { Badge, Button, money, Segmented } from './components/ui'
import { useAsync } from './hooks/useAsync'
import { api, errorMessage } from './lib/api'
import { CODESPACES_URL, REPO_URL, STATIC_DEMO } from './lib/demo'
import { useTheme } from './lib/theme'
import Accounts from './pages/Accounts'
import Budget from './pages/Budget'
import House from './pages/House'
import Investments from './pages/Investments'
import Overview from './pages/Overview'
import Savings from './pages/Savings'
import Spending from './pages/Spending'
import Transactions from './pages/Transactions'

const TABS = [
  { to: '/', label: 'Overview', Icon: LineChart, end: true },
  { to: '/spending', label: 'Spending', Icon: Banknote, end: false },
  { to: '/budget', label: 'Budget', Icon: Target, end: false },
  { to: '/transactions', label: 'Transactions', Icon: CreditCard, end: false },
  { to: '/savings', label: 'Find Savings', Icon: Scissors, end: false },
  { to: '/investments', label: 'Investments', Icon: PiggyBank, end: false },
  { to: '/house', label: 'Buying a House', Icon: Home, end: false },
  { to: '/accounts', label: 'Accounts', Icon: Wallet, end: false },
]

export default function App() {
  const { choice, setChoice } = useTheme()
  const [syncing, setSyncing] = useState(false)
  const [syncNote, setSyncNote] = useState<string | null>(null)
  const [version, setVersion] = useState(0)

  const health = useAsync(() => api.health(), [version])
  const worth = useAsync(() => api.accounts().then((r) => r.net_worth), [version])

  async function sync() {
    setSyncing(true)
    setSyncNote(null)
    try {
      const result = await api.syncAll()
      const failed = result.failed ?? []
      setSyncNote(
        failed.length
          ? `${failed.length} connection(s) failed: ${failed.map((f: { error: string }) => f.error).join('; ')}`
          : 'Synced.',
      )
      setVersion((v) => v + 1)
    } catch (e) {
      setSyncNote(errorMessage(e))
    } finally {
      setSyncing(false)
      setTimeout(() => setSyncNote(null), 6000)
    }
  }

  return (
    <div className="min-h-full">
      {STATIC_DEMO && <PreviewBar />}
      <header
        className="sticky top-0 z-20 border-b backdrop-blur"
        // Not Tailwind's bg-[var(--surface-1)]/95: an opacity modifier cannot
        // be applied to a variable holding a hex colour, so that class emitted
        // nothing and the header was fully transparent over scrolled content.
        style={{
          borderColor: 'var(--border)',
          background: 'color-mix(in srgb, var(--surface-1) 94%, transparent)',
        }}
      >
        <div className="mx-auto flex max-w-[1400px] flex-wrap items-center gap-x-5 gap-y-2 px-4 py-2.5">
          <div className="flex items-baseline gap-2.5">
            <span className="text-sm font-semibold tracking-tight">Finance</span>
            {worth.data && (
              <span className="text-sm text-[var(--text-secondary)]">
                net worth{' '}
                <span className="font-semibold text-[var(--text-primary)]">
                  {money(worth.data.net_worth, false)}
                </span>
              </span>
            )}
          </div>

          <div className="ml-auto flex items-center gap-2">
            {syncNote && (
              <span className="max-w-sm truncate text-xs text-[var(--text-muted)]">{syncNote}</span>
            )}
            {health.data?.is_demo && <Badge tone="info">Demo data</Badge>}
            <Button onClick={sync} size="sm" disabled={syncing}>
              <RefreshCw size={13} className={syncing ? 'animate-spin' : undefined} />
              {syncing ? 'Syncing' : 'Sync'}
            </Button>
            <Segmented
              size="sm"
              value={choice}
              onChange={setChoice}
              options={[
                { value: 'light', label: '☀' },
                { value: 'dark', label: '☾' },
                { value: 'system', label: '⌗' },
              ]}
            />
          </div>
        </div>

        {health.data?.is_demo && (
          <div
            className="border-t px-4 py-1.5"
            style={{ borderColor: 'var(--border)', background: 'var(--accent-wash)' }}
          >
            <div className="mx-auto flex max-w-[1400px] flex-wrap items-center gap-x-3 gap-y-1 text-xs">
              <span className="text-[var(--text-secondary)]">
                Showing generated demo data so every tab works before you link anything. Numbers
                here are invented.
              </span>
              <button
                onClick={async () => {
                  if (!window.confirm(
                    'Delete the demo accounts and all 1,700-odd demo transactions?\n\nThis leaves an empty database ready for your real accounts, and will not come back on restart.',
                  )) return
                  try {
                    await api.clearDemo()
                    setVersion((v) => v + 1)
                  } catch (e) {
                    setSyncNote(errorMessage(e))
                  }
                }}
                className="font-medium underline underline-offset-2 hover:no-underline"
                style={{ color: 'var(--series-1)' }}
              >
                Clear it and start fresh
              </button>
            </div>
          </div>
        )}

        <nav className="mx-auto max-w-[1400px] px-4">
          <ul className="-mb-px flex gap-1 overflow-x-auto" role="tablist">
            {TABS.map(({ to, label, Icon, end }) => (
              <li key={to}>
                <NavLink
                  to={to}
                  end={end}
                  className={({ isActive }) =>
                    clsx(
                      'flex items-center gap-1.5 whitespace-nowrap border-b-2 px-3 py-2.5 text-sm font-medium transition-colors',
                      isActive
                        ? 'border-[var(--series-1)] text-[var(--text-primary)]'
                        : 'border-transparent text-[var(--text-muted)] hover:text-[var(--text-secondary)]',
                    )
                  }
                >
                  <Icon size={14} />
                  {label}
                </NavLink>
              </li>
            ))}
          </ul>
        </nav>
      </header>

      <main className="mx-auto max-w-[1400px] px-4 py-5">
        <Routes>
          <Route path="/" element={<Overview version={version} />} />
          <Route path="/spending" element={<Spending version={version} />} />
          <Route path="/budget" element={<Budget version={version} />} />
          <Route path="/transactions" element={<Transactions version={version} />} />
          <Route path="/savings" element={<Savings version={version} />} />
          <Route path="/investments" element={<Investments version={version} />} />
          <Route path="/house" element={<House version={version} />} />
          <Route
            path="/accounts"
            element={<Accounts version={version} onChanged={() => setVersion((v) => v + 1)} />}
          />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </main>

      <footer
        className="mx-auto max-w-[1400px] border-t px-4 py-4 text-xs text-[var(--text-muted)]"
        style={{ borderColor: 'var(--border)' }}
      >
        <div className="flex flex-wrap items-center gap-x-4 gap-y-1">
          <span className="inline-flex items-center gap-1">
            {choice === 'system' ? <Monitor size={11} /> : choice === 'dark' ? <Moon size={11} /> : <Sun size={11} />}
            Local-only: data stays in {health.data?.database ?? 'finance.db'} on this machine.
          </span>
          {health.data && (
            <span className="tnum">
              {health.data.accounts} accounts · {health.data.transactions.toLocaleString()} transactions
              {health.data.latest_transaction ? ` · latest ${health.data.latest_transaction}` : ''}
            </span>
          )}
          {health.data && !health.data.master_key_from_environment && (
            <Badge tone="warning">FINANCE_MASTER_KEY not set</Badge>
          )}
        </div>
      </footer>
    </div>
  )
}

/**
 * Only on the GitHub Pages preview: says what this is before anyone mistakes
 * the numbers for something real, and points at the version that saves.
 */
function PreviewBar() {
  return (
    <div
      className="flex flex-wrap items-center justify-center gap-x-3 gap-y-1 px-4 py-2 text-center text-xs"
      style={{ background: 'var(--accent-wash)', color: 'var(--text-secondary)' }}
    >
      <span>
        <strong className="text-[var(--text-primary)]">Live preview</strong> — made-up data, read-only.
      </span>
      <a href={CODESPACES_URL} target="_blank" rel="noreferrer"
         className="font-medium text-[var(--text-primary)] underline">
        Run the full app in Codespaces
      </a>
      <a href={REPO_URL} target="_blank" rel="noreferrer" className="underline">
        Source on GitHub
      </a>
    </div>
  )
}
