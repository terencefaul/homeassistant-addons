import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwind from '@tailwindcss/vite'

// The guest bundle deliberately has NO PWA plugin.
//
// Offline is meaningless for a gate -- the action requires the network by
// definition -- and a service worker would give this public origin persistent
// code execution on every visitor's phone, outliving the credential that got
// them there. Unlike an ordinary bug it cannot be fixed forward: a service
// worker that ships once keeps running on devices that never come back.
//
// This is a SEPARATE config from the admin build on purpose. A single shared
// config with a flag is how a service worker eventually reaches the public
// origin by accident. tests/test_frontend_build.py asserts the built output
// contains no service worker.
export default defineConfig({
  root: 'guest',
  // MUST be absolute, not './'. The guest page is served from the domain root
  // but is also reached at /g/<token>, and a relative base makes the browser
  // ask for /g/assets/... which does not exist -- the page loads and then
  // renders nothing. The admin bundle is the opposite case: ingress serves it
  // under a path that changes, so it needs './'.
  base: '/',
  plugins: [react(), tailwind()],
  build: {
    outDir: '../dist/guest',
    emptyOutDir: true,
    target: 'es2020',
    // Small enough to load on one bar of signal at a gate.
    chunkSizeWarningLimit: 250,
  },
})
