/**
 * Shared UI primitives.
 *
 * Two rules from the design method are enforced here rather than left to each
 * page: status is never colour-alone (every Badge pairs its colour with an icon
 * and a word), and large standalone figures use proportional digits while
 * columns of numbers use tabular ones.
 */

import clsx from 'clsx'
import {
  AlertTriangle, ArrowDown, ArrowUp, Check, CircleDot, Info, Loader2, Minus, X,
} from 'lucide-react'
import type { ReactNode } from 'react'

import { money, moneyCompact, num, signedPct } from '../lib/format'

// ---------------------------------------------------------------------------

export function Card({
  children, className, padded = true,
}: { children: ReactNode; className?: string; padded?: boolean }) {
  return (
    <div
      className={clsx(
        'rounded-xl border bg-[var(--surface-1)]',
        padded && 'p-4',
        className,
      )}
      style={{ borderColor: 'var(--border)' }}
    >
      {children}
    </div>
  )
}

export function CardHeader({
  title, subtitle, action,
}: { title: string; subtitle?: string; action?: ReactNode }) {
  return (
    <div className="mb-3 flex items-start justify-between gap-3">
      <div className="min-w-0">
        <h3 className="text-sm font-semibold text-[var(--text-primary)]">{title}</h3>
        {subtitle && (
          <p className="mt-0.5 text-xs text-[var(--text-muted)]">{subtitle}</p>
        )}
      </div>
      {action && <div className="shrink-0">{action}</div>}
    </div>
  )
}

export function SectionTitle({ children, hint }: { children: ReactNode; hint?: string }) {
  return (
    <div className="mb-3 mt-6 first:mt-0">
      <h2 className="text-base font-semibold text-[var(--text-primary)]">{children}</h2>
      {hint && <p className="mt-1 text-xs text-[var(--text-muted)]">{hint}</p>}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Figures. Proportional digits: tabular-nums makes 121 look loose at size.
// ---------------------------------------------------------------------------

export function Hero({
  label, value, delta, deltaLabel, footnote, upIsGood = true,
}: {
  label: string
  value: string
  delta?: number | null
  deltaLabel?: string
  footnote?: string
  upIsGood?: boolean
}) {
  return (
    <div>
      <div className="text-xs font-medium uppercase tracking-wide text-[var(--text-muted)]">
        {label}
      </div>
      <div className="mt-1 text-5xl font-semibold leading-none text-[var(--text-primary)]">
        {value}
      </div>
      {(delta !== undefined && delta !== null) && (
        <div className="mt-2">
          <Delta value={delta} label={deltaLabel} upIsGood={upIsGood} />
        </div>
      )}
      {footnote && <p className="mt-2 text-xs text-[var(--text-muted)]">{footnote}</p>}
    </div>
  )
}

export function Delta({
  value, label, upIsGood = true, asPercent = true,
}: { value: number; label?: string; upIsGood?: boolean; asPercent?: boolean }) {
  const flat = Math.abs(value) < 0.05
  const good = flat ? null : value > 0 === upIsGood
  const Icon = flat ? Minus : value > 0 ? ArrowUp : ArrowDown
  const color = flat
    ? 'var(--text-muted)'
    : good ? 'var(--success-text)' : 'var(--danger-text)'
  return (
    <span className="inline-flex items-center gap-1 text-xs font-medium" style={{ color }}>
      <Icon size={13} strokeWidth={2.5} />
      <span className="tnum">
        {asPercent ? signedPct(Math.abs(value) < 0.05 ? 0 : value) : money(Math.abs(value))}
      </span>
      {label && <span className="font-normal text-[var(--text-muted)]">{label}</span>}
    </span>
  )
}

export function StatTile({
  label, value, delta, deltaLabel, upIsGood = true, sub, children, accent,
}: {
  label: string
  value: string
  delta?: number | null
  deltaLabel?: string
  upIsGood?: boolean
  sub?: string
  children?: ReactNode
  accent?: boolean
}) {
  return (
    <div
      className={clsx(
        'rounded-xl border p-3.5',
        accent ? 'bg-[var(--accent-wash)]' : 'bg-[var(--surface-1)]',
      )}
      style={{ borderColor: 'var(--border)' }}
    >
      <div className="text-xs font-medium text-[var(--text-muted)]">{label}</div>
      <div className="mt-1 text-2xl font-semibold leading-tight text-[var(--text-primary)]">
        {value}
      </div>
      {(delta !== undefined && delta !== null) && (
        <div className="mt-1">
          <Delta value={delta} label={deltaLabel} upIsGood={upIsGood} />
        </div>
      )}
      {sub && <div className="mt-1 text-xs text-[var(--text-muted)]">{sub}</div>}
      {children && <div className="mt-2">{children}</div>}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Meter. The fill carries severity; the track is a lighter step of the ramp.
// ---------------------------------------------------------------------------

export function Meter({
  value, max, severity = 'auto', label, right, height = 8, overflowLabel,
}: {
  value: number
  max: number
  severity?: 'auto' | 'accent' | 'good' | 'warning' | 'critical'
  label?: string
  right?: ReactNode
  height?: number
  overflowLabel?: string
}) {
  const ratio = max > 0 ? value / max : 0
  const clamped = Math.min(1, Math.max(0, ratio))
  const resolved = severity === 'auto'
    ? ratio > 1 ? 'critical' : ratio > 0.85 ? 'warning' : 'accent'
    : severity
  const fill = {
    accent: 'var(--series-1)',
    good: 'var(--status-good)',
    warning: 'var(--status-warning)',
    critical: 'var(--status-critical)',
  }[resolved]

  return (
    <div>
      {(label || right) && (
        <div className="mb-1.5 flex items-baseline justify-between gap-2 text-xs">
          <span className="truncate text-[var(--text-secondary)]">{label}</span>
          <span className="shrink-0 tnum text-[var(--text-muted)]">{right}</span>
        </div>
      )}
      <div
        className="w-full overflow-hidden rounded-full"
        style={{ height, background: 'var(--seq-100)' }}
        role="meter"
        aria-valuenow={Math.round(value)}
        aria-valuemin={0}
        aria-valuemax={Math.round(max)}
        aria-label={label}
      >
        <div
          className="h-full rounded-full transition-[width] duration-500"
          style={{ width: `${clamped * 100}%`, background: fill }}
        />
      </div>
      {ratio > 1 && overflowLabel && (
        <div className="mt-1 flex items-center gap-1 text-xs" style={{ color: 'var(--danger-text)' }}>
          <AlertTriangle size={12} strokeWidth={2.5} />
          <span>{overflowLabel}</span>
        </div>
      )}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Status. Colour never carries the meaning alone — always an icon and a word.
// ---------------------------------------------------------------------------

type Tone = 'good' | 'warning' | 'serious' | 'critical' | 'neutral' | 'info'

const TONES: Record<Tone, { color: string; bg: string; Icon: typeof Check }> = {
  good: { color: 'var(--status-good)', bg: 'rgba(12,163,12,0.12)', Icon: Check },
  warning: { color: 'var(--status-warning)', bg: 'rgba(250,178,25,0.14)', Icon: AlertTriangle },
  serious: { color: 'var(--status-serious)', bg: 'rgba(236,131,90,0.14)', Icon: AlertTriangle },
  critical: { color: 'var(--status-critical)', bg: 'rgba(208,59,59,0.12)', Icon: X },
  neutral: { color: 'var(--text-secondary)', bg: 'var(--surface-2)', Icon: CircleDot },
  info: { color: 'var(--series-1)', bg: 'var(--accent-wash)', Icon: Info },
}

export function Badge({
  tone = 'neutral', children, icon = true,
}: { tone?: Tone; children: ReactNode; icon?: boolean }) {
  const { color, bg, Icon } = TONES[tone]
  return (
    <span
      className="inline-flex items-center gap-1 rounded-md px-1.5 py-0.5 text-xs font-medium"
      style={{ color, background: bg }}
    >
      {icon && <Icon size={11} strokeWidth={2.5} />}
      {children}
    </span>
  )
}

export function Banner({
  tone = 'info', title, children, onDismiss,
}: { tone?: Tone; title?: string; children: ReactNode; onDismiss?: () => void }) {
  const { color, bg, Icon } = TONES[tone]
  return (
    <div
      className="flex items-start gap-2.5 rounded-lg p-3 text-sm"
      style={{ background: bg, color: 'var(--text-primary)' }}
    >
      <Icon size={15} strokeWidth={2.5} style={{ color, marginTop: 1, flexShrink: 0 }} />
      <div className="min-w-0 flex-1">
        {title && <div className="font-semibold">{title}</div>}
        <div className={clsx('text-[var(--text-secondary)]', title && 'mt-0.5')}>{children}</div>
      </div>
      {onDismiss && (
        <button
          onClick={onDismiss}
          className="shrink-0 rounded p-0.5 text-[var(--text-muted)] hover:text-[var(--text-primary)]"
          aria-label="Dismiss"
        >
          <X size={14} />
        </button>
      )}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Tables. Wide tables scroll inside their own container, never the page.
// ---------------------------------------------------------------------------

export interface Column<T> {
  key: string
  header: string
  align?: 'left' | 'right'
  width?: string
  render: (row: T) => ReactNode
  /** Numeric columns align on their digits. */
  numeric?: boolean
}

export function DataTable<T>({
  columns, rows, rowKey, empty = 'Nothing to show.', onRowClick, dense = false, footer,
}: {
  columns: Column<T>[]
  rows: T[]
  rowKey: (row: T, index: number) => string | number
  empty?: string
  onRowClick?: (row: T) => void
  dense?: boolean
  footer?: ReactNode
}) {
  if (!rows.length) {
    return (
      <div className="py-8 text-center text-sm text-[var(--text-muted)]">{empty}</div>
    )
  }
  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-full border-collapse text-sm">
        <thead>
          <tr>
            {columns.map((c) => (
              <th
                key={c.key}
                className={clsx(
                  'whitespace-nowrap border-b pb-2 text-xs font-medium text-[var(--text-muted)]',
                  c.align === 'right' ? 'text-right' : 'text-left',
                )}
                style={{ borderColor: 'var(--border)', width: c.width }}
              >
                {c.header}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row, i) => (
            <tr
              key={rowKey(row, i)}
              onClick={onRowClick ? () => onRowClick(row) : undefined}
              className={clsx(
                'border-b last:border-0',
                onRowClick && 'cursor-pointer hover:bg-[var(--surface-2)]',
              )}
              style={{ borderColor: 'var(--border)' }}
            >
              {columns.map((c) => (
                <td
                  key={c.key}
                  className={clsx(
                    dense ? 'py-1.5' : 'py-2.5',
                    c.align === 'right' ? 'text-right' : 'text-left',
                    c.numeric && 'tnum',
                  )}
                >
                  {c.render(row)}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
        {footer && <tfoot>{footer}</tfoot>}
      </table>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Controls
// ---------------------------------------------------------------------------

export function Button({
  children, onClick, variant = 'secondary', size = 'md', disabled, type = 'button', className,
}: {
  children: ReactNode
  onClick?: () => void
  variant?: 'primary' | 'secondary' | 'ghost' | 'danger'
  size?: 'sm' | 'md'
  disabled?: boolean
  type?: 'button' | 'submit'
  className?: string
}) {
  const styles = {
    primary: 'text-white',
    secondary: 'text-[var(--text-primary)] bg-[var(--surface-2)] border',
    ghost: 'text-[var(--text-secondary)] hover:bg-[var(--surface-2)]',
    danger: 'text-white',
  }[variant]
  const bg = variant === 'primary' ? 'var(--series-1)'
    : variant === 'danger' ? 'var(--status-critical)' : undefined
  return (
    <button
      type={type}
      onClick={onClick}
      disabled={disabled}
      className={clsx(
        'inline-flex items-center justify-center gap-1.5 rounded-lg font-medium transition-opacity',
        size === 'sm' ? 'px-2.5 py-1.5 text-xs' : 'px-3.5 py-2 text-sm',
        styles,
        disabled && 'cursor-not-allowed opacity-50',
        className,
      )}
      style={{ background: bg, borderColor: 'var(--border)' }}
    >
      {children}
    </button>
  )
}

export function Segmented<T extends string | number>({
  options, value, onChange, size = 'md',
}: {
  options: { value: T; label: ReactNode }[]
  value: T
  onChange: (next: T) => void
  size?: 'sm' | 'md'
}) {
  return (
    <div
      className="inline-flex rounded-lg border p-0.5"
      style={{ borderColor: 'var(--border)', background: 'var(--surface-2)' }}
      role="tablist"
    >
      {options.map((o) => {
        const active = o.value === value
        return (
          <button
            key={String(o.value)}
            role="tab"
            aria-selected={active}
            onClick={() => onChange(o.value)}
            className={clsx(
              'rounded-md font-medium transition-colors',
              size === 'sm' ? 'px-2 py-1 text-xs' : 'px-2.5 py-1.5 text-xs',
              active
                ? 'bg-[var(--surface-1)] text-[var(--text-primary)] shadow-sm'
                : 'text-[var(--text-muted)] hover:text-[var(--text-secondary)]',
            )}
          >
            {o.label}
          </button>
        )
      })}
    </div>
  )
}

export function Field({
  label, hint, children, suffix,
}: { label: string; hint?: string; children: ReactNode; suffix?: string }) {
  return (
    <label className="block">
      <span className="mb-1 block text-xs font-medium text-[var(--text-secondary)]">{label}</span>
      <div className="relative">
        {children}
        {suffix && (
          <span className="pointer-events-none absolute right-2.5 top-1/2 -translate-y-1/2 text-xs text-[var(--text-muted)]">
            {suffix}
          </span>
        )}
      </div>
      {hint && <span className="mt-1 block text-xs text-[var(--text-muted)]">{hint}</span>}
    </label>
  )
}

export function NumberInput({
  value, onChange, step = 1, min, max, suffix, prefix,
}: {
  value: number
  onChange: (next: number) => void
  step?: number
  min?: number
  max?: number
  suffix?: string
  prefix?: string
}) {
  return (
    <div className="relative">
      {prefix && (
        <span className="pointer-events-none absolute left-2.5 top-1/2 -translate-y-1/2 text-sm text-[var(--text-muted)]">
          {prefix}
        </span>
      )}
      <input
        type="number"
        value={Number.isFinite(value) ? value : ''}
        step={step}
        min={min}
        max={max}
        onChange={(e) => {
          const next = e.target.valueAsNumber
          if (Number.isFinite(next)) onChange(next)
          else if (e.target.value === '') onChange(0)
        }}
        className={clsx(
          'tnum w-full rounded-lg border bg-[var(--surface-1)] py-2 text-sm text-[var(--text-primary)]',
          'outline-none focus:ring-2',
          prefix ? 'pl-6' : 'pl-2.5',
          suffix ? 'pr-9' : 'pr-2.5',
        )}
        style={{ borderColor: 'var(--border)' }}
      />
      {suffix && (
        <span className="pointer-events-none absolute right-2.5 top-1/2 -translate-y-1/2 text-xs text-[var(--text-muted)]">
          {suffix}
        </span>
      )}
    </div>
  )
}

export function TextInput({
  value, onChange, placeholder, type = 'text',
}: {
  value: string
  onChange: (next: string) => void
  placeholder?: string
  type?: string
}) {
  return (
    <input
      type={type}
      value={value}
      placeholder={placeholder}
      onChange={(e) => onChange(e.target.value)}
      className="w-full rounded-lg border bg-[var(--surface-1)] px-2.5 py-2 text-sm text-[var(--text-primary)] outline-none placeholder:text-[var(--text-muted)] focus:ring-2"
      style={{ borderColor: 'var(--border)' }}
    />
  )
}

export function Select<T extends string>({
  value, onChange, options, placeholder,
}: {
  value: T
  onChange: (next: T) => void
  options: { value: T; label: string }[]
  placeholder?: string
}) {
  return (
    <select
      value={value}
      onChange={(e) => onChange(e.target.value as T)}
      className="w-full rounded-lg border bg-[var(--surface-1)] px-2.5 py-2 text-sm text-[var(--text-primary)] outline-none focus:ring-2"
      style={{ borderColor: 'var(--border)' }}
    >
      {placeholder && <option value="">{placeholder}</option>}
      {options.map((o) => (
        <option key={o.value} value={o.value}>{o.label}</option>
      ))}
    </select>
  )
}

export function Slider({
  value, onChange, min, max, step = 1, label, display,
}: {
  value: number
  onChange: (next: number) => void
  min: number
  max: number
  step?: number
  label: string
  display: string
}) {
  return (
    <div>
      <div className="mb-1 flex items-baseline justify-between gap-2">
        <span className="text-xs font-medium text-[var(--text-secondary)]">{label}</span>
        <span className="tnum text-xs font-semibold text-[var(--text-primary)]">{display}</span>
      </div>
      <input
        type="range"
        min={min}
        max={max}
        step={step}
        value={value}
        onChange={(e) => onChange(e.target.valueAsNumber)}
        className="w-full"
        aria-label={label}
      />
    </div>
  )
}

// ---------------------------------------------------------------------------
// States
// ---------------------------------------------------------------------------

export function Loading({ label = 'Loading' }: { label?: string }) {
  return (
    <div className="flex items-center justify-center gap-2 py-16 text-sm text-[var(--text-muted)]">
      <Loader2 size={15} className="animate-spin" />
      {label}…
    </div>
  )
}

export function ErrorState({ message, onRetry }: { message: string; onRetry?: () => void }) {
  return (
    <Card className="mx-auto max-w-xl">
      <Banner tone="critical" title="Something went wrong">{message}</Banner>
      {onRetry && (
        <div className="mt-3">
          <Button onClick={onRetry} variant="secondary" size="sm">Try again</Button>
        </div>
      )}
    </Card>
  )
}

export function EmptyState({
  title, children, action,
}: { title: string; children?: ReactNode; action?: ReactNode }) {
  return (
    <div className="py-12 text-center">
      <p className="text-sm font-medium text-[var(--text-primary)]">{title}</p>
      {children && (
        <p className="mx-auto mt-1 max-w-md text-sm text-[var(--text-muted)]">{children}</p>
      )}
      {action && <div className="mt-4 flex justify-center">{action}</div>}
    </div>
  )
}

/**
 * A swatch + label key. Used wherever a chart's colours need naming outside the
 * chart itself, and as the relief for the three light-mode hues that sit below
 * 3:1 against the surface.
 */
export function LegendKey({
  items,
}: { items: { label: string; colorIndex: number; value?: string }[] }) {
  return (
    <ul className="flex flex-wrap gap-x-4 gap-y-1.5">
      {items.map((i) => (
        <li key={i.label} className="flex items-center gap-1.5 text-xs">
          <span
            className="inline-block h-2 w-2 shrink-0 rounded-sm"
            style={{ background: `var(--series-${i.colorIndex + 1})` }}
          />
          <span className="text-[var(--text-secondary)]">{i.label}</span>
          {i.value && <span className="tnum text-[var(--text-muted)]">{i.value}</span>}
        </li>
      ))}
    </ul>
  )
}

export { money, moneyCompact, num }
