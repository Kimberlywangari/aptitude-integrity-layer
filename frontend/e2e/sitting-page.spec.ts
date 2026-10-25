import { expect, test } from '@playwright/test'
import { START_ERRORS } from '../src/candidate/copy'
import { EMAIL, PASSWORD, signInAsAdmin } from './admin'

// A sitting's own page, in a real browser: click a sitting in the list, see who has opened their
// link and who has not, then delete the sitting and find its codes dead.
//
// Run it against a scratch database (it creates and then deletes a sitting, and uses up a code).
// See sittings.spec.ts for the settings.

test('click a sitting to see who was invited, then delete it and its codes stop working', async ({
  browser,
}) => {
  test.skip(!EMAIL || !PASSWORD, 'set E2E_ADMIN_EMAIL and E2E_ADMIN_PASSWORD')

  const admin = await (await browser.newContext()).newPage()
  await signInAsAdmin(admin)

  // ---- a small practice sitting, with three codes
  const name = `e2e page ${Date.now()}`
  await admin.goto('/admin')
  await admin.locator('#new-sitting').waitFor()
  await admin.getByText('Practice questions', { exact: true }).click()
  await admin.locator('#name').fill(name)
  await admin.locator('input[id^="per-"]').first().waitFor()
  for (const input of await admin.locator('input[id^="per-"]').all()) {
    await input.fill('1')
    await input.blur()
  }
  await admin.getByRole('button', { name: 'Create sitting' }).click()
  const row = admin.locator('tbody tr', { hasText: name })
  await expect(row).toBeVisible({ timeout: 20_000 })

  await admin.goto('/admin/invites')
  const option = admin.locator('#sitting option', { hasText: name }).first()
  await option.waitFor({ state: 'attached' })
  await admin.locator('#sitting').selectOption((await option.getAttribute('value')) ?? '')
  await admin.locator('#count').fill('3')
  await admin.getByRole('button', { name: 'Generate codes' }).click()
  await expect(admin.getByText(`For "${name}".`)).toBeVisible()
  const codes = (await admin.locator('td.mono').allTextContents())
    .map((text) => text.trim())
    .filter((text) => /^[0-9A-Z]{4}-[0-9A-Z]{4}$/.test(text))
  expect(codes).toHaveLength(3)

  // ---- one of them opens their link; the other two never do
  const candidate = await (await browser.newContext()).newPage()
  await candidate.goto(`/?t=${codes[0]}`)
  await candidate.getByRole('button', { name: 'Continue', exact: true }).click()
  await expect(candidate).toHaveURL(/\/precheck/)

  // ---- the admin clicks the sitting's row (not its name) and sees who is where
  await admin.goto('/admin')
  await expect(row).toBeVisible()
  await row.locator('td').nth(1).click()
  await expect(admin).toHaveURL(/\/admin\/sittings\/\d+$/)
  await expect(admin.locator('#sitting-name')).toHaveText(name)
  // the heading is matched whole: "Opened" is also inside "Not opened"
  const tile = (label: string) =>
    admin
      .locator('.tile')
      .filter({ has: admin.getByRole('heading', { name: label, exact: true }) })
      .locator('.tile-n')
  await expect(tile('Invited')).toHaveText('3')
  await expect(tile('Not opened')).toHaveText('2')
  await expect(tile('Opened')).toHaveText('1')

  const people = admin.locator('.table tbody tr')
  await expect(people).toHaveCount(3)
  await admin.getByRole('button', { name: 'Not opened 2' }).click()
  await expect(people).toHaveCount(2)
  await admin.getByRole('button', { name: 'Opened 1' }).click()
  await expect(people).toHaveCount(1)
  await expect(people.first()).toContainText('Opened')

  // ---- delete it: the name has to be typed, then the sitting and its codes are gone
  await admin.getByRole('button', { name: 'Delete sitting' }).click()
  const confirm = admin.getByRole('button', { name: 'Delete for good' })
  await expect(confirm).toBeDisabled()
  await admin.locator('#confirm-name').fill(name)
  await expect(confirm).toBeEnabled()
  await confirm.click()
  await expect(admin).toHaveURL(/\/admin$/)
  await expect(admin.locator('tbody tr', { hasText: name })).toHaveCount(0)

  const stranger = await (await browser.newContext()).newPage()
  await stranger.goto(`/?t=${codes[1]}`)
  await stranger.getByRole('button', { name: 'Continue', exact: true }).click()
  await expect(stranger.getByRole('alert')).toContainText(START_ERRORS.invalid_invitation)
})
