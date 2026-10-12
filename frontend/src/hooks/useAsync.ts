/** Data fetching with the states every tab needs, and no skeleton flash. */

import { useCallback, useEffect, useRef, useState } from 'react'

import { errorMessage } from '../lib/api'

export interface AsyncState<T> {
  data: T | null
  error: string | null
  /** True only on the first load. Refetches keep the previous render. */
  loading: boolean
  /** True while a refetch is in flight with data already on screen. */
  refreshing: boolean
  reload: () => void
  setData: (next: T) => void
}

export function useAsync<T>(fetcher: () => Promise<T>, deps: unknown[] = []): AsyncState<T> {
  const [data, setData] = useState<T | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)
  const [refreshing, setRefreshing] = useState(false)
  const [tick, setTick] = useState(0)

  // A stale response from a superseded request must not overwrite a newer one.
  const requestId = useRef(0)
  const hasData = useRef(false)

  const fetcherRef = useRef(fetcher)
  fetcherRef.current = fetcher

  useEffect(() => {
    const id = ++requestId.current
    if (hasData.current) setRefreshing(true)
    else setLoading(true)

    fetcherRef.current()
      .then((result) => {
        if (id !== requestId.current) return
        setData(result)
        hasData.current = true
        setError(null)
      })
      .catch((e) => {
        if (id !== requestId.current) return
        setError(errorMessage(e))
      })
      .finally(() => {
        if (id !== requestId.current) return
        setLoading(false)
        setRefreshing(false)
      })
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [...deps, tick])

  const reload = useCallback(() => setTick((t) => t + 1), [])

  return { data, error, loading, refreshing, reload, setData }
}

/**
 * A value that settles after `delay` ms of quiet.
 *
 * Sliders fire continuously while dragged. Without this, dragging the interest
 * rate across its range issues a request per frame — the last response wins
 * anyway, so all but one is wasted work.
 */
export function useDebounced<T>(value: T, delay = 250): T {
  const [settled, setSettled] = useState(value)
  useEffect(() => {
    const id = setTimeout(() => setSettled(value), delay)
    return () => clearTimeout(id)
  }, [value, delay])
  return settled
}
