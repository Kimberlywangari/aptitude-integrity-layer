import react from '@vitejs/plugin-react'
import { defineConfig } from 'vitest/config'

// One origin for UI and API: the dev proxy keeps /api on the page's own host and port, which
// matters because SEB's request hash covers the exact URL (master plan A6).
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    strictPort: true,
    proxy: {
      '/api': 'http://localhost:8000',
    },
  },
  test: {
    environment: 'jsdom',
    include: ['tests/**/*.test.{ts,tsx}'],
  },
})
