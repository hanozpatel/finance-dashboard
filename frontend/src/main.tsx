import React, { useEffect, useState } from 'react'
import ReactDOM from 'react-dom/client'
import { BrowserRouter } from 'react-router-dom'

import App from './App'
import { BOOT_STEPS, BROWSER_APP, boot, type BootStep } from './lib/runtime'
import { ThemeProvider } from './lib/theme'
import './index.css'

/**
 * The web build has to start Python before the first request can be answered,
 * so it shows where it is rather than a blank page. A first visit downloads
 * the runtime (cached afterwards); a return visit is about two seconds.
 */
function BootGate({ children }: { children: React.ReactNode }) {
  const [step, setStep] = useState<BootStep>('runtime')
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    boot(setStep).catch((e: unknown) => setError(e instanceof Error ? e.message : String(e)))
  }, [])

  if (step === 'ready') return <>{children}</>

  const current = BOOT_STEPS.findIndex((s) => s.step === step)
  return (
    <div className="flex min-h-screen items-center justify-center px-4" style={{ background: 'var(--surface-page)' }}>
      <div className="w-full max-w-sm">
        <h1 className="text-lg font-semibold text-[var(--text-primary)]">Finance Dashboard</h1>
        <p className="mt-1 text-sm text-[var(--text-secondary)]">
          Starting up in your browser. Everything runs on this device — your data is never sent anywhere.
        </p>
        <ol className="mt-5 space-y-2 text-sm">
          {BOOT_STEPS.map((s, i) => (
            <li key={s.step} className="flex items-center gap-2"
                style={{ color: i <= current ? 'var(--text-primary)' : 'var(--text-muted)' }}>
              <span aria-hidden className="inline-block w-4 text-center">
                {i < current ? '✓' : i === current && !error ? '…' : '·'}
              </span>
              {s.label}
            </li>
          ))}
        </ol>
        {error ? (
          <p className="mt-5 text-sm" style={{ color: 'var(--danger-text)' }} role="alert">{error}</p>
        ) : (
          <p className="mt-5 text-xs text-[var(--text-muted)]">
            The first visit downloads about 12 MB; after that it starts in a couple of seconds.
          </p>
        )}
      </div>
    </div>
  )
}

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <ThemeProvider>
      {/* The web build is served from /<repo>/, not the domain root. */}
      <BrowserRouter basename={import.meta.env.BASE_URL}>
        {BROWSER_APP ? <BootGate><App /></BootGate> : <App />}
      </BrowserRouter>
    </ThemeProvider>
  </React.StrictMode>,
)
