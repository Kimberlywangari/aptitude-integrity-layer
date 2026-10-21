import { defineConfig } from '@playwright/test'

// A real browser walking the whole candidate journey against a running stack. It needs one:
//   E2E_BASE_URL  where the app is served (default http://localhost:8080, the Compose `web` address)
//   E2E_TOKEN     an unused invitation code
// Run it against a scratch database, because it uses up the invitation and leaves a recording
// behind. Chromium's fake camera and a generated tone stand in for the devices (see e2e/journey.spec.ts).
export default defineConfig({
  testDir: 'e2e',
  timeout: 240_000,
  workers: 1,
  fullyParallel: false,
  reporter: 'list',
  use: {
    baseURL: process.env.E2E_BASE_URL ?? 'http://localhost:8080',
    headless: true,
    trace: 'retain-on-failure',
  },
})
