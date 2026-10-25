import { mkdtempSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { expect, test } from '@playwright/test'
import type { Page } from '@playwright/test'
import { DEVICE_NOTICE_CHECKBOX, NOTIFICATIONS_CHECKBOX, START_ERRORS } from '../src/candidate/copy'
import { EMAIL, PASSWORD, signInAsAdmin } from './admin'

// Each kind of sitting, end to end, through the real screens and a real server: an admin makes the
// sitting, makes a code for it on the Invitations page, and a candidate who opens that code sits
// exactly that sitting, with its sections, its number of questions and its time (1.75 minutes each).
//
//   E2E_BASE_URL        where the app is served (default http://localhost:8080)
//   E2E_ADMIN_EMAIL     an admin account (python -m scripts.jobs create_reviewer --role admin)
//   E2E_ADMIN_PASSWORD  its password
//   E2E_AI=1            also try a sitting whose questions an AI writes (needs the model running; slow)
//
// Run it against a scratch database: it creates sittings and uses up the codes it makes. The
// "cytonn" case needs Cytonn's questions loaded (python -m scripts.jobs fetch_cytonn_bank).

const WITH_AI = process.env.E2E_AI === '1'

interface Plan {
  mode: 'cytonn' | 'practice' | 'ai'
  radio: string // the words beside the radio button
  counts: Record<string, number>
}

const PLANS: Plan[] = [
  {
    mode: 'cytonn',
    radio: "Cytonn's questions",
    counts: {
      numerical: 3,
      logical: 2,
      'error checking': 2,
      verbal: 2,
      'critical thinking': 1,
      'ai competence': 1,
      'office assistant': 1,
    },
  },
  { mode: 'practice', radio: 'Practice questions', counts: { numerical: 2, verbal: 3 } },
  ...(WITH_AI
    ? [
        {
          mode: 'ai' as const,
          radio: 'Written by AI for each candidate',
          counts: { numerical: 1, logical: 1 },
        },
      ]
    : []),
]

/** A 16-bit mono WAV of a steady tone: the fake microphone, loud enough to pass the voice check. */
function toneFile(): string {
  const rate = 16_000
  const samples = rate * 10
  const buffer = Buffer.alloc(44 + samples * 2)
  buffer.write('RIFF', 0)
  buffer.writeUInt32LE(36 + samples * 2, 4)
  buffer.write('WAVEfmt ', 8)
  buffer.writeUInt32LE(16, 16)
  buffer.writeUInt16LE(1, 20)
  buffer.writeUInt16LE(1, 22)
  buffer.writeUInt32LE(rate, 24)
  buffer.writeUInt32LE(rate * 2, 28)
  buffer.writeUInt16LE(2, 32)
  buffer.writeUInt16LE(16, 34)
  buffer.write('data', 36)
  buffer.writeUInt32LE(samples * 2, 40)
  for (let i = 0; i < samples; i++) {
    buffer.writeInt16LE(Math.round(Math.sin((2 * Math.PI * 440 * i) / rate) * 0.4 * 32767), 44 + i * 2)
  }
  const file = join(mkdtempSync(join(tmpdir(), 'tone-')), 'tone.wav')
  writeFileSync(file, buffer)
  return file
}

test.use({
  permissions: ['camera', 'microphone'],
  launchOptions: {
    args: [
      '--use-fake-ui-for-media-stream',
      '--use-fake-device-for-media-stream',
      `--use-file-for-fake-audio-capture=${toneFile()}`,
    ],
  },
})

/** Fill the sitting form for a plan and create it. Returns the sitting's name. */
async function makeSitting(page: Page, plan: Plan): Promise<string> {
  const name = `e2e ${plan.mode} ${Date.now()}`
  await page.goto('/admin')
  await page.locator('#new-sitting').waitFor()
  await page.getByText(plan.radio, { exact: true }).click()
  await page.locator('#name').fill(name)

  if (plan.mode === 'ai') {
    await page.locator('#ai-numerical').waitFor()
    for (const input of await page.locator('input[id^="ai-"]').all()) {
      const section = ((await input.getAttribute('id')) ?? '').slice(3).replace(/-/g, ' ')
      await input.fill(String(plan.counts[section] ?? 0))
      await input.blur()
    }
  } else {
    await page.locator('input[id^="per-"]').first().waitFor()
    for (const input of await page.locator('input[id^="per-"]').all()) {
      const section = ((await input.getAttribute('id')) ?? '').slice(4).replace(/-/g, ' ')
      await input.fill(String(plan.counts[section] ?? 0))
      await input.blur()
    }
  }
  await page.getByRole('button', { name: 'Create sitting' }).click()
  await expect(page.locator('tbody tr', { hasText: name })).toBeVisible({ timeout: 20_000 })
  return name
}

/** Make one code for the sitting on the Invitations page and read it off the screen. */
async function makeCode(page: Page, sittingName: string): Promise<string> {
  await page.goto('/admin/invites')
  const option = page.locator('#sitting option', { hasText: sittingName }).first()
  await option.waitFor({ state: 'attached' })
  await page.locator('#sitting').selectOption((await option.getAttribute('value')) ?? '')
  await page.locator('#count').fill('1')
  await page.getByRole('button', { name: 'Generate codes' }).click()
  await expect(page.getByText(`For "${sittingName}".`)).toBeVisible()
  const code = (await page.locator('td.mono').first().textContent())?.trim() ?? ''
  expect(code).toMatch(/^[0-9A-Z]{4}-[0-9A-Z]{4}$/)
  return code
}

async function passThePreCheck(page: Page) {
  await page.getByText(DEVICE_NOTICE_CHECKBOX).click()
  await page.getByRole('button', { name: 'Continue', exact: true }).click()
  await page.getByText(NOTIFICATIONS_CHECKBOX).click()
  await page.getByRole('button', { name: 'Continue', exact: true }).click()
  await page.getByRole('button', { name: 'Allow camera and microphone' }).click()
  await expect(page.getByRole('button', { name: 'Continue', exact: true })).toBeEnabled({
    timeout: 15_000,
  })
  await page.getByRole('button', { name: 'Continue', exact: true }).click()
  await page.getByRole('button', { name: 'Go full screen' }).click()
  await page.getByRole('button', { name: 'Continue', exact: true }).click()
  await page.getByRole('button', { name: 'Continue to the test' }).click()
}

for (const plan of PLANS) {
  test(`${plan.mode}: the candidate sits exactly the sitting their code was made for`, async ({
    browser,
  }) => {
    test.skip(!EMAIL || !PASSWORD, 'set E2E_ADMIN_EMAIL and E2E_ADMIN_PASSWORD')
    test.setTimeout(plan.mode === 'ai' ? 900_000 : 240_000)

    // ---- the admin: a sitting, then a code for it
    const admin = await (await browser.newContext()).newPage()
    await signInAsAdmin(admin)
    const name = await makeSitting(admin, plan)
    const code = await makeCode(admin, name)

    // ---- the candidate opens that code and nothing else tells the page which sitting it is
    const context = await browser.newContext({ permissions: ['camera', 'microphone'] })
    const page = await context.newPage()
    await page.goto(`/?t=${code}`)
    await page.getByRole('button', { name: 'Continue', exact: true }).click()
    await expect(page).toHaveURL(/\/precheck/)
    await passThePreCheck(page)

    await expect(page).toHaveURL(/\/integrity/)
    await page.getByText('I have read and agree to the statement above.').click()
    const start = page.getByRole('button', { name: 'I agree, start the test' })
    // an AI sitting writes the questions first: the button opens up when they are ready
    await expect(start).toBeEnabled({ timeout: plan.mode === 'ai' ? 600_000 : 30_000 })
    await start.click()
    await expect(page).toHaveURL(/\/test/, { timeout: 45_000 })

    // ---- the paper is the sitting's: its size, its sections, its time
    const total = Object.values(plan.counts).reduce((n, v) => n + v, 0)
    const header = page.locator('.count')
    await expect(header).toContainText(`Question 1 of ${total}`)
    const [minutes, seconds] = ((await page.locator('[role=timer]').textContent()) ?? '0:0')
      .trim()
      .split(':')
      .map(Number)
    const whole = total * 105 // 1.75 minutes a question
    expect(minutes * 60 + seconds).toBeGreaterThan(whole - 45)
    expect(minutes * 60 + seconds).toBeLessThanOrEqual(whole)
    // and each question has its own clock, counting down from 1 min 45 s
    await expect(page.locator('.qtimer')).toContainText(/This question 01:\d\d/)

    const seen: string[] = []
    let pictures = 0
    for (let position = 1; position <= total; position++) {
      await expect(header).toContainText(`Question ${position} of ${total}`)
      seen.push(((await page.locator('.chip.section').textContent()) ?? '').trim())
      for (const image of await page.locator('#question-text img').all()) {
        pictures += 1
        // the picture really arrived: a broken link has no width
        await expect
          .poll(() => image.evaluate((el) => (el as HTMLImageElement).naturalWidth), {
            timeout: 15_000,
          })
          .toBeGreaterThan(0)
      }
      await page.locator('label.option').first().click()
      await page.getByRole('button', { name: 'Submit' }).click()
    }

    const expected = Object.entries(plan.counts).flatMap(([section, n]) =>
      Array<string>(n).fill(section),
    )
    expect(seen.sort()).toEqual(expected.sort())
    if (plan.mode === 'cytonn') {
      expect(pictures).toBeGreaterThan(0) // numerical, logical and error checking carry pictures
    }

    await expect(page).toHaveURL(/\/done/, { timeout: 30_000 })
    await expect(page.getByText('Test finished')).toBeVisible()
  })
}

test('an invited person starts with their code and their email, and not without the email', async ({
  browser,
}) => {
  test.skip(!EMAIL || !PASSWORD, 'set E2E_ADMIN_EMAIL and E2E_ADMIN_PASSWORD')
  test.setTimeout(240_000)

  // ---- the admin pastes a list; the person gets one code with their email attached
  const admin = await (await browser.newContext()).newPage()
  await signInAsAdmin(admin)
  const name = await makeSitting(admin, PLANS.find((p) => p.mode === 'practice') as Plan)
  await admin.goto('/admin/invites')
  const option = admin.locator('#sitting option', { hasText: name }).first()
  await option.waitFor({ state: 'attached' })
  await admin.locator('#sitting').selectOption((await option.getAttribute('value')) ?? '')
  await admin.locator('#people').fill('Ada Lovelace, Ada.Lovelace@Example.org')
  await admin.getByRole('button', { name: 'Check the list' }).click()
  await expect(admin.getByText('1 person is ready to invite')).toBeVisible()
  await admin.getByRole('button', { name: 'Create invitations and send emails' }).click()
  await expect(admin.getByText(`For "${name}".`)).toBeVisible()
  const code = (await admin.locator('td.mono').first().textContent())?.trim() ?? ''
  expect(code).toMatch(/^[0-9A-Z]{4}-[0-9A-Z]{4}$/)

  // ---- the link fills in the code; the wrong email is refused, the right one (any case) starts
  const page = await (await browser.newContext({ permissions: ['camera', 'microphone'] })).newPage()
  await page.goto(`/?t=${code}`)
  await expect(page.locator('#invitation')).toHaveValue(code)
  await page.locator('#email').fill('someone@else.test')
  await page.getByRole('button', { name: 'Continue', exact: true }).click()
  await expect(page.getByRole('alert')).toContainText(START_ERRORS.invalid_invitation)

  // ---- the right pair (any case) is a first time: they are asked to choose a password
  await page.locator('#email').fill('ada.lovelace@example.org')
  await page.getByRole('button', { name: 'Continue', exact: true }).click()
  await expect(page.getByText('Now choose a password')).toBeVisible()
  await page.locator('#new-password').fill('a password of her own')
  await page.locator('#repeat-password').fill('a password of her own')
  await page.getByRole('button', { name: 'Create password and continue' }).click()
  await expect(page).toHaveURL(/\/precheck/)

  // ---- next time, email and password are enough: no code, and the same test comes back
  const again = await (await browser.newContext({ permissions: ['camera', 'microphone'] })).newPage()
  await again.goto('/candidate')
  await again.locator('#email').fill('ada.lovelace@example.org')
  await again.locator('#password').fill('not her password')
  await again.getByRole('button', { name: 'Continue', exact: true }).click()
  await expect(again.getByRole('alert')).toContainText(START_ERRORS.invalid_invitation)
  await again.locator('#password').fill('a password of her own')
  await again.getByRole('button', { name: 'Continue', exact: true }).click()
  await expect(again).toHaveURL(/\/precheck/)
})
