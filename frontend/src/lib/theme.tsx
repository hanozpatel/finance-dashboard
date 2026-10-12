/**
 * Theme state and the chart colour tokens derived from it.
 *
 * Colours live in CSS (index.css) rather than here, so there is exactly one
 * definition of the palette. This reads the resolved values back out of the
 * document for ECharts, which needs real hex strings and cannot consume custom
 * properties. The read is keyed on the resolved theme, so a toggle re-reads.
 */

import {
  createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode,
} from 'react'

export type ThemeChoice = 'light' | 'dark' | 'system'
export type ResolvedTheme = 'light' | 'dark'

const STORAGE_KEY = 'finance-dashboard-theme'

interface ThemeContextValue {
  choice: ThemeChoice
  resolved: ResolvedTheme
  setChoice: (next: ThemeChoice) => void
}

const ThemeContext = createContext<ThemeContextValue>({
  choice: 'system',
  resolved: 'light',
  setChoice: () => {},
})

function systemTheme(): ResolvedTheme {
  return window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light'
}

export function ThemeProvider({ children }: { children: ReactNode }) {
  const [choice, setChoiceState] = useState<ThemeChoice>(
    () => (localStorage.getItem(STORAGE_KEY) as ThemeChoice) || 'system',
  )
  const [system, setSystem] = useState<ResolvedTheme>(systemTheme)

  useEffect(() => {
    const mq = window.matchMedia('(prefers-color-scheme: dark)')
    const onChange = () => setSystem(mq.matches ? 'dark' : 'light')
    mq.addEventListener('change', onChange)
    return () => mq.removeEventListener('change', onChange)
  }, [])

  const resolved: ResolvedTheme = choice === 'system' ? system : choice

  useEffect(() => {
    // 'system' removes the attribute entirely so the CSS media query governs —
    // stamping data-theme="light" would defeat it.
    if (choice === 'system') document.documentElement.removeAttribute('data-theme')
    else document.documentElement.setAttribute('data-theme', choice)
  }, [choice])

  const setChoice = useCallback((next: ThemeChoice) => {
    localStorage.setItem(STORAGE_KEY, next)
    setChoiceState(next)
  }, [])

  const value = useMemo(() => ({ choice, resolved, setChoice }), [choice, resolved, setChoice])
  return <ThemeContext.Provider value={value}>{children}</ThemeContext.Provider>
}

export function useTheme() {
  return useContext(ThemeContext)
}

export interface ChartTokens {
  theme: ResolvedTheme
  /** The validated categorical order. Assigned by index, never cycled. */
  series: string[]
  sequential: string[]
  surface: string
  grid: string
  axis: string
  textPrimary: string
  textSecondary: string
  textMuted: string
  border: string
  status: { good: string; warning: string; serious: string; critical: string }
}

function readVar(name: string, fallback: string): string {
  const value = getComputedStyle(document.documentElement).getPropertyValue(name).trim()
  return value || fallback
}

/** Resolved chart colours for the active theme. */
export function useChartTokens(): ChartTokens {
  const { resolved } = useTheme()
  return useMemo(() => {
    const dark = resolved === 'dark'
    return {
      theme: resolved,
      series: [
        readVar('--series-1', dark ? '#3987e5' : '#2a78d6'),
        readVar('--series-2', dark ? '#d95926' : '#eb6834'),
        readVar('--series-3', dark ? '#199e70' : '#1baf7a'),
        readVar('--series-4', dark ? '#c98500' : '#eda100'),
        readVar('--series-5', dark ? '#d55181' : '#e87ba4'),
        readVar('--series-6', '#008300'),
        readVar('--series-7', dark ? '#9085e9' : '#4a3aa7'),
        readVar('--series-8', dark ? '#e66767' : '#e34948'),
      ],
      sequential: [
        readVar('--seq-100', dark ? '#0d366b' : '#cde2fb'),
        readVar('--seq-250', dark ? '#184f95' : '#86b6ef'),
        readVar('--seq-400', dark ? '#256abf' : '#3987e5'),
        readVar('--seq-450', dark ? '#3987e5' : '#2a78d6'),
        readVar('--seq-550', dark ? '#6da7ec' : '#1c5cab'),
        readVar('--seq-700', dark ? '#cde2fb' : '#0d366b'),
      ],
      surface: readVar('--surface-1', dark ? '#1a1a19' : '#fcfcfb'),
      grid: readVar('--grid', dark ? '#2c2c2a' : '#e1e0d9'),
      axis: readVar('--axis', dark ? '#383835' : '#c3c2b7'),
      textPrimary: readVar('--text-primary', dark ? '#ffffff' : '#0b0b0b'),
      textSecondary: readVar('--text-secondary', dark ? '#c3c2b7' : '#52514e'),
      textMuted: readVar('--text-muted', '#898781'),
      border: dark ? 'rgba(255,255,255,0.1)' : 'rgba(11,11,11,0.1)',
      status: {
        good: readVar('--status-good', '#0ca30c'),
        warning: readVar('--status-warning', '#fab219'),
        serious: readVar('--status-serious', '#ec835a'),
        critical: readVar('--status-critical', '#d03b3b'),
      },
    }
  }, [resolved])
}
