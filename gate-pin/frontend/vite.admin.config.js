import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwind from '@tailwindcss/vite'
import { VitePWA } from 'vite-plugin-pwa'

// The admin panel DOES get the full PWA treatment. Every argument against one
// on the guest page inverts here: it is used repeatedly by one known person,
// it sits behind Home Assistant ingress rather than on a public origin, and
// having it on the home screen is genuinely useful.
export default defineConfig({
  root: 'admin',
  base: './',
  plugins: [
    react(),
    tailwind(),
    VitePWA({
      registerType: 'autoUpdate',
      manifest: {
        name: 'Gate PIN admin',
        short_name: 'Gate PIN',
        description: 'Mint and revoke guest access',
        theme_color: '#18181b',
        background_color: '#18181b',
        display: 'standalone',
        icons: [
          { src: 'icon-192.png', sizes: '192x192', type: 'image/png' },
          { src: 'icon-512.png', sizes: '512x512', type: 'image/png' },
        ],
      },
      workbox: {
        globPatterns: ['**/*.{js,css,html,svg,png}'],
        // Shell only. Never cache API responses: a stale grant list or audit
        // log is worse than no answer.
        navigateFallbackDenylist: [/^\/api\//],
        runtimeCaching: [],
      },
    }),
  ],
  build: {
    outDir: '../dist/admin',
    emptyOutDir: true,
    target: 'es2020',
  },
})
