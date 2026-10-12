import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// Ports come from the environment so two checkouts can run side by side — the
// Makefile passes them through, and `local.mk` (untracked) can override them
// per checkout. The backend defaults to 8001 so it cannot collide with
// anything already bound to 8000.
const frontendPort = Number(process.env.FRONTEND_PORT ?? 5174)
const backendPort = Number(process.env.BACKEND_PORT ?? 8001)

export default defineConfig({
  plugins: [react()],
  // The static demo is served from https://<user>.github.io/<repo>/, so its
  // assets need that prefix; everywhere else the app lives at the root.
  base: process.env.VITE_BASE ?? '/',
  server: {
    port: frontendPort,
    // Fail loudly rather than drift to another port the proxy and the docs do
    // not know about.
    strictPort: true,
    // Codespaces serves the dev server from *.app.github.dev, which Vite's
    // DNS-rebinding guard would otherwise reject.
    allowedHosts: ['localhost', '127.0.0.1', '.app.github.dev'],
    proxy: {
      '/api': { target: `http://127.0.0.1:${backendPort}`, changeOrigin: true },
    },
  },
})
