/**
 * The static preview's "backend": every request answered from a snapshot.
 *
 * Built only when VITE_STATIC_DEMO=1 (the GitHub Pages build). The snapshot is
 * produced by backend/scripts/build_static_demo.py against freshly seeded demo
 * data, and fetched at runtime from public/ so ordinary builds never need it.
 *
 * Reads resolve three ways, most specific first:
 *   1. an exact match on path and query;
 *   2. transactions, filtered and paged here by a mirror of the backend query —
 *      the one view with too many combinations to precompute;
 *   3. the closest recorded response for the same path, so a request the
 *      snapshot did not anticipate degrades to sensible data rather than an
 *      error screen.
 *
 * Writes are refused with a message the existing error banners already know how
 * to show, pointing at Codespaces, where the same app runs for real.
 */

import { AxiosError, AxiosHeaders, type AxiosResponse, type InternalAxiosRequestConfig } from 'axios'

export const STATIC_DEMO = import.meta.env.VITE_STATIC_DEMO === '1'

export const REPO_URL = 'https://github.com/hanozpatel/finance-dashboard'
export const CODESPACES_URL = 'https://codespaces.new/hanozpatel/finance-dashboard?quickstart=1'

const READ_ONLY =
  'This is a read-only preview with made-up data, so changes are not saved. '
  + 'Open it in GitHub Codespaces (link at the top) to run the full app and try editing.'

interface Snapshot {
  generated: string
  responses: Record<string, unknown>
  transactions: Record<string, unknown>[]
}

let snapshot: Promise<Snapshot> | null = null

function load(): Promise<Snapshot> {
  snapshot ??= fetch(`${import.meta.env.BASE_URL}demo/snapshot.json`).then((r) => {
    if (!r.ok) throw new Error(`Could not load the preview data (${r.status}).`)
    return r.json()
  })
  return snapshot
}

export function snapshotDate(): Promise<string> {
  return load().then((s) => s.generated)
}

/** Path and query from an axios config, query merged and sorted. */
function parse(config: InternalAxiosRequestConfig): { path: string; params: Record<string, string> } {
  const [path, query = ''] = (config.url ?? '').split('?')
  const params: Record<string, string> = {}
  new URLSearchParams(query).forEach((v, k) => { params[k] = v })
  for (const [k, v] of Object.entries(config.params ?? {})) {
    if (v !== undefined && v !== null && v !== '') params[k] = String(v)
  }
  return { path, params }
}

function keyOf(path: string, params: Record<string, string>): string {
  const keys = Object.keys(params).sort()
  return keys.length ? `${path}?${keys.map((k) => `${k}=${params[k]}`).join('&')}` : path
}

function respond<T>(config: InternalAxiosRequestConfig, data: T, status = 200): AxiosResponse<T> {
  return { data, status, statusText: 'OK', headers: new AxiosHeaders(), config, request: null }
}

function fail(config: InternalAxiosRequestConfig, status: number, detail: string): never {
  const response = respond(config, { detail }, status)
  throw new AxiosError(detail, String(status), config, null, response)
}

/** Mirror of backend routers/transactions.py list_transactions. */
function filterTransactions(rows: Record<string, unknown>[], p: Record<string, string>) {
  const truthy = (v?: string) => v === 'true' || v === '1'
  let out = rows.filter((t) => {
    const amount = t.amount as number
    if (p.start && (t.date as string) < p.start) return false
    if (p.end && (t.date as string) > p.end) return false
    if (p.category && t.category !== p.category) return false
    if (p.subcategory && t.subcategory !== p.subcategory) return false
    if (p.account_id && String(t.account_id) !== p.account_id) return false
    if (p.merchant_key && t.merchant_key !== p.merchant_key) return false
    if (p.search) {
      const needle = p.search.toLowerCase()
      const hay = [t.description, t.merchant, t.notes].map((v) => String(v ?? '').toLowerCase())
      if (!hay.some((h) => h.includes(needle))) return false
    }
    if (p.min_amount && Math.abs(amount) < Number(p.min_amount)) return false
    if (p.max_amount && Math.abs(amount) > Number(p.max_amount)) return false
    if (!truthy(p.include_transfers) && t.is_transfer) return false
    if (truthy(p.recurring_only) && t.recurring_id == null) return false
    if (truthy(p.uncategorized_only) && t.category !== 'Uncategorized') return false
    return true
  })

  const sort = (p.sort ?? 'date') as 'date' | 'amount' | 'merchant' | 'category'
  const dir = p.direction === 'asc' ? 1 : -1
  out = [...out].sort((a, b) => {
    const x = a[sort] as string | number
    const y = b[sort] as string | number
    if (x < y) return -dir
    if (x > y) return dir
    return (b.id as number) - (a.id as number)
  })

  const limit = Number(p.limit ?? 100)
  const offset = Number(p.offset ?? 0)
  const outflow = out.reduce((s, t) => s + Math.min(0, t.amount as number), 0) * -1
  const inflow = out.reduce((s, t) => s + Math.max(0, t.amount as number), 0)
  const page = out.slice(offset, offset + limit)
  return {
    transactions: page,
    total_count: out.length,
    outflow: Math.round(outflow * 100) / 100,
    inflow: Math.round(inflow * 100) / 100,
    net: Math.round((inflow - outflow) * 100) / 100,
    limit,
    offset,
    has_more: offset + page.length < out.length,
  }
}

/** The recorded response for this path whose query shares the most values. */
function closest(responses: Record<string, unknown>, path: string, params: Record<string, string>) {
  let best: { score: number; value: unknown } | null = null
  for (const [key, value] of Object.entries(responses)) {
    const [p, q = ''] = key.split('?')
    if (p !== path) continue
    const recorded = new URLSearchParams(q)
    let score = 0
    for (const [k, v] of Object.entries(params)) if (recorded.get(k) === v) score += 1
    if (!best || score > best.score) best = { score, value }
  }
  return best?.value
}

export async function demoAdapter(config: InternalAxiosRequestConfig): Promise<AxiosResponse> {
  const method = (config.method ?? 'get').toLowerCase()
  if (method !== 'get') fail(config, 403, READ_ONLY)

  const data = await load()
  const { path, params } = parse(config)

  if (path === '/api/transactions') {
    return respond(config, filterTransactions(data.transactions, params))
  }

  const exact = data.responses[keyOf(path, params)]
  if (exact !== undefined) return respond(config, exact)

  const near = closest(data.responses, path, params)
  if (near !== undefined) return respond(config, near)

  fail(config, 404, 'The preview has no data for this view. Open the full app in Codespaces.')
}
