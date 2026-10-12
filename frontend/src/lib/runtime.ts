/**
 * Where the backend runs.
 *
 * Normally it is a FastAPI server on localhost and this file does nothing. In
 * the web build (VITE_BROWSER_APP=1, what GitHub Pages serves) the *same*
 * Python backend runs inside the browser tab instead: Pyodide — CPython compiled
 * to WebAssembly — loads the backend's source, and every request axios makes is
 * handed to it as a function call rather than sent over a network.
 *
 * The database is a SQLite file in the browser's own storage (IndexedDB). It
 * never leaves the device: there is no server to send it to. That is also why
 * this file owns backup, restore, and delete — in a browser, "your data" is only
 * as durable as the browser's storage, so getting a copy out has to be easy.
 */

import { AxiosError, AxiosHeaders, type AxiosResponse, type InternalAxiosRequestConfig } from 'axios'

export const BROWSER_APP = import.meta.env.VITE_BROWSER_APP === '1'

export const REPO_URL = 'https://github.com/hanozpatel/finance-dashboard'
export const INSTALL_URL = `${REPO_URL}#install-it-for-automatic-bank-sync`

// Pinned: a Pyodide upgrade changes the Python version and every package, and
// should be a deliberate, tested change rather than whatever the CDN serves.
const PYODIDE_VERSION = '0.29.5'
const PYODIDE_URL = `https://cdn.jsdelivr.net/pyodide/v${PYODIDE_VERSION}/full/`
const PACKAGES = ['fastapi', 'pydantic', 'sqlite3', 'cryptography', 'micropip']
const PURE_PYTHON = ['python-multipart', 'python-dotenv']
const DATA_DIR = '/data'
const DB_FILE = `${DATA_DIR}/finance.db`
const FRESH_START_KEY = 'finance-fresh-start'

/* Minimal typing for the parts of Pyodide used here. */
interface PyProxy { toJs(opts?: object): unknown; destroy(): void }
interface Pyodide {
  loadPackage(names: string[]): Promise<void>
  runPythonAsync(code: string): Promise<unknown>
  pyimport(name: string): Record<string, (...args: unknown[]) => Promise<PyProxy> | PyProxy>
  toPy(value: unknown): unknown
  unpackArchive(buffer: ArrayBuffer, format: string, opts: { extractDir: string }): void
  FS: {
    mkdirTree(path: string): void
    mount(type: unknown, opts: object, path: string): void
    syncfs(populate: boolean, cb: (err: unknown) => void): void
    writeFile(path: string, data: Uint8Array): void
    unlink(path: string): void
    readdir(path: string): string[]
    filesystems: { IDBFS: unknown }
  }
}
declare global {
  interface Window { loadPyodide?: (opts: { indexURL: string }) => Promise<Pyodide> }
}

export type BootStep = 'runtime' | 'packages' | 'storage' | 'app' | 'ready'
export const BOOT_STEPS: { step: BootStep; label: string }[] = [
  { step: 'runtime', label: 'Loading Python into your browser' },
  { step: 'packages', label: 'Loading the libraries it needs' },
  { step: 'storage', label: 'Opening your data on this device' },
  { step: 'app', label: 'Starting the app' },
]

let pyodide: Pyodide | null = null
let booting: Promise<void> | null = null

function loadScript(src: string): Promise<void> {
  return new Promise((resolve, reject) => {
    const s = document.createElement('script')
    s.src = src
    s.onload = () => resolve()
    s.onerror = () => reject(new Error('Could not download the Python runtime. Check your connection and reload.'))
    document.head.appendChild(s)
  })
}

function syncfs(populate: boolean): Promise<void> {
  return new Promise((resolve, reject) => {
    pyodide!.FS.syncfs(populate, (err) => (err ? reject(err) : resolve()))
  })
}

/** Start the in-browser backend once; later calls share the same promise. */
export function boot(onStep: (step: BootStep) => void = () => {}): Promise<void> {
  booting ??= (async () => {
    onStep('runtime')
    await loadScript(`${PYODIDE_URL}pyodide.js`)
    const py = await window.loadPyodide!({ indexURL: PYODIDE_URL })
    pyodide = py

    onStep('packages')
    await py.loadPackage(PACKAGES)
    await py.runPythonAsync(`import micropip\nawait micropip.install(${JSON.stringify(PURE_PYTHON)})`)

    onStep('storage')
    py.FS.mkdirTree(DATA_DIR)
    py.FS.mount(py.FS.filesystems.IDBFS, {}, DATA_DIR)
    await syncfs(true)

    onStep('app')
    const bundle = await fetch(`${import.meta.env.BASE_URL}py/backend.zip`)
    if (!bundle.ok) throw new Error(`Could not load the app (${bundle.status}).`)
    py.unpackArchive(await bundle.arrayBuffer(), 'zip', { extractDir: '/app' })
    // Set by "delete all my data": start empty instead of re-seeding the demo.
    let fresh = false
    try {
      fresh = localStorage.getItem(FRESH_START_KEY) === '1'
      localStorage.removeItem(FRESH_START_KEY)
    } catch { /* storage blocked: default to the normal first run */ }
    await py.runPythonAsync(
      `import sys\nsys.path.insert(0, '/app')\nimport browser_bridge\nbrowser_bridge.start(fresh=${fresh ? 'True' : 'False'})`,
    )
    // The first visit seeds demo data; keep it.
    await syncfs(false)
    onStep('ready')
  })()
  return booting
}

/* Requests are run one at a time. A tab is single-threaded anyway, and
   serialising keeps one request's database writes from interleaving with
   another's across an await. */
let queue: Promise<unknown> = Promise.resolve()

async function bodyBytes(config: InternalAxiosRequestConfig): Promise<{ bytes: Uint8Array; type?: string }> {
  const data = config.data
  if (data === undefined || data === null) return { bytes: new Uint8Array() }
  if (typeof FormData !== 'undefined' && data instanceof FormData) {
    // Let the browser produce real multipart bytes, boundary and all.
    const req = new Request('http://local/', { method: 'POST', body: data })
    return { bytes: new Uint8Array(await req.arrayBuffer()), type: req.headers.get('content-type') ?? undefined }
  }
  const text = typeof data === 'string' ? data : JSON.stringify(data)
  return { bytes: new TextEncoder().encode(text), type: 'application/json' }
}

function splitUrl(config: InternalAxiosRequestConfig): { path: string; query: string } {
  const [path, inline = ''] = (config.url ?? '').split('?')
  const params = new URLSearchParams(inline)
  for (const [k, v] of Object.entries(config.params ?? {})) {
    if (v !== undefined && v !== null && v !== '') params.set(k, String(v))
  }
  return { path, query: params.toString() }
}

async function run(config: InternalAxiosRequestConfig): Promise<AxiosResponse> {
  await boot()
  const py = pyodide!
  const method = (config.method ?? 'get').toUpperCase()
  const { path, query } = splitUrl(config)
  const { bytes, type } = await bodyBytes(config)
  const headers: [string, string][] = type ? [['content-type', type]] : []

  const bridge = py.pyimport('browser_bridge')
  const result = (await bridge.handle(method, path, query, py.toPy(headers), py.toPy(bytes))) as PyProxy
  const [status, rawHeaders, payload] = result.toJs() as [number, [string, string][], Uint8Array]
  result.destroy()

  if (method !== 'GET') await syncfs(false)

  const contentType = rawHeaders.find(([k]) => k === 'content-type')?.[1] ?? ''
  const text = new TextDecoder().decode(payload)
  const data = contentType.includes('json') && text ? JSON.parse(text) : text
  const response: AxiosResponse = {
    data, status, statusText: String(status), headers: new AxiosHeaders(Object.fromEntries(rawHeaders)),
    config, request: null,
  }
  if (status >= 400) {
    throw new AxiosError(`Request failed with status code ${status}`, String(status), config, null, response)
  }
  return response
}

export function browserAdapter(config: InternalAxiosRequestConfig): Promise<AxiosResponse> {
  const next = queue.then(() => run(config))
  queue = next.catch(() => undefined)
  return next
}

// ---------------------------------------------------------------------------
// Your data, in this browser
// ---------------------------------------------------------------------------

/** Download the whole database as a file the user keeps. */
export async function downloadBackup(): Promise<void> {
  await boot()
  await queue
  const bridge = pyodide!.pyimport('browser_bridge')
  const proxy = bridge.export_database() as PyProxy
  const bytes = proxy.toJs() as Uint8Array
  proxy.destroy()
  const url = URL.createObjectURL(new Blob([new Uint8Array(bytes)], { type: 'application/vnd.sqlite3' }))
  const a = document.createElement('a')
  a.href = url
  a.download = `finance-backup-${new Date().toISOString().slice(0, 10)}.db`
  document.body.appendChild(a)
  a.click()
  a.remove()
  setTimeout(() => URL.revokeObjectURL(url), 5000)
}

/** Replace everything with a backup file, then reload into it. */
export async function restoreBackup(file: File): Promise<void> {
  const bytes = new Uint8Array(await file.arrayBuffer())
  // SQLite files start with this exact 16-byte header; anything else is not a backup.
  const magic = new TextDecoder().decode(bytes.slice(0, 15))
  if (magic !== 'SQLite format 3') throw new Error('That file is not a Finance Dashboard backup.')
  await boot()
  await queue
  pyodide!.FS.writeFile(DB_FILE, bytes)
  await syncfs(false)
  window.location.reload()
}

/** Delete every trace of the data from this browser, then start fresh. */
export async function deleteAllData(): Promise<void> {
  await boot()
  await queue
  for (const name of pyodide!.FS.readdir(DATA_DIR)) {
    if (name !== '.' && name !== '..') pyodide!.FS.unlink(`${DATA_DIR}/${name}`)
  }
  await syncfs(false)
  try { localStorage.setItem(FRESH_START_KEY, '1') } catch { /* reload re-seeds the demo instead */ }
  window.location.reload()
}
