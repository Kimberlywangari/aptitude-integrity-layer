import type { Page } from '@playwright/test'

// Shared by the browser tests that start as an admin.
//   E2E_ADMIN_EMAIL     an admin account (python -m scripts.jobs create_reviewer --role admin)
//   E2E_ADMIN_PASSWORD  its password
export const EMAIL = process.env.E2E_ADMIN_EMAIL
export const PASSWORD = process.env.E2E_ADMIN_PASSWORD

export async function signInAsAdmin(page: Page) {
  await page.goto('/login/admin')
  await page.locator('#email').fill(EMAIL ?? '')
  await page.locator('#password').fill(PASSWORD ?? '')
  await page.locator('form').evaluate((form) => (form as HTMLFormElement).requestSubmit())
  // signed in once the page has left the sign-in address (/login/admin also contains "/admin")
  await page.waitForURL((url) => !url.pathname.startsWith('/login'), { timeout: 20_000 })
}
