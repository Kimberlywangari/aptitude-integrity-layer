import vue from '@vitejs/plugin-vue'
import { defineConfig } from 'vitest/config'

// One origin for UI and API: the dev proxy keeps /api on the page's own host and port, so the
// browser makes no cross-origin requests (master plan A6). API_URL points it at another API (for
// example a second instance on a scratch database); it defaults to the usual local one.
const api = process.env.API_URL ?? 'http://localhost:8000'

export default defineConfig({
  plugins: [vue()],
  server: {
    port: 5173,
    strictPort: true,
    proxy: {
      '/api': api,
    },
  },
  test: {
    environment: 'jsdom',
    include: ['tests/**/*.test.ts'],
    setupFiles: ['tests/setup.ts'],
  },
})
