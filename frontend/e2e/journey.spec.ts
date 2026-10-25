import { mkdtempSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { expect, test } from '@playwright/test'
import type { Page } from '@playwright/test'
import {
  DEVICE_NOTICE_CHECKBOX,
  FINISHED_LEAVE,
  FINISHED_LEAVE_BUTTON,
  FINISHED_TITLE,
  FLAG_NOTICE,
  NOTIFICATIONS_CHECKBOX,
  UPLOAD_DONE,
} from '../src/candidate/copy'

// One candidate takes the whole test in a real browser, against the real server with the strict
// gate on (PRECHECK_GATE=recording): invitation link, every permission, the recording starting
// before the clock does, twelve questions with one skipped, a reload in the middle, a spell with
// no network, the finish and the upload to the very last chunk.
//
// The camera is Chromium's fake one and the microphone plays a generated tone, so it runs anywhere.
// It cannot stand in for a real Edge, a Mac, a physically muted microphone or a real bad network.

const TOKEN = process.env.E2E_TOKEN
const EMAIL = process.env.E2E_EMAIL // only if the invitation was made for an email
const SKIPPED = 5 // the question the candidate skips
const OFFLINE_FOR_MS = 20_000

/** A 16-bit mono WAV of a steady tone: the fake microphone, loud enough to pass the voice check. */
function toneFile(): string {
  const rate = 16_000
  const seconds = 10
  const samples = rate * seconds
  const buffer = Buffer.alloc(44 + samples * 2)
  buffer.write('RIFF', 0)
  buffer.writeUInt32LE(36 + samples * 2, 4)
  buffer.write('WAVEfmt ', 8)
  buffer.writeUInt32LE(16, 16)
  buffer.writeUInt16LE(1, 20) // PCM
  buffer.writeUInt16LE(1, 22) // mono
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

async function passThePreCheck(page: Page) {
  await page.getByText(DEVICE_NOTICE_CHECKBOX).click()
  await page.getByRole('button', { name: 'Continue', exact: true }).click()
  await page.getByText(NOTIFICATIONS_CHECKBOX).click()
  await page.getByRole('button', { name: 'Continue', exact: true }).click()
  await page.getByRole('button', { name: 'Allow camera and microphone' }).click()
  // the tone is heard, then the step can be left
  await expect(page.getByRole('button', { name: 'Continue', exact: true })).toBeEnabled({ timeout: 15_000 })
  await page.getByRole('button', { name: 'Continue', exact: true }).click()
  await page.getByRole('button', { name: 'Go full screen' }).click()
  await page.getByRole('button', { name: 'Continue', exact: true }).click()
  await page.getByRole('button', { name: 'Continue to the test' }).click()
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

test('a candidate takes the whole test, recorded and logged, and everything arrives', async ({
  page,
  context,
}) => {
  test.skip(!TOKEN, 'set E2E_TOKEN to an unused invitation code (and E2E_BASE_URL if not :8080)')
  page.on('dialog', (dialog) => void dialog.accept()) // "leave this page?" when it is reloaded

  // ---- the invitation link, the pre-check, and the recording starting before the clock
  await page.goto(`/?t=${TOKEN}`) // the link fills in the code; the candidate presses Continue
  if (EMAIL) await page.locator('#email').fill(EMAIL)
  await page.getByRole('button', { name: 'Continue', exact: true }).click()
  await expect(page).toHaveURL(/\/precheck/)
  await passThePreCheck(page)

  await expect(page).toHaveURL(/\/integrity/)
  await page.getByText('I have read and agree to the statement above.').click()
  await page.getByRole('button', { name: 'I agree, start the test' }).click()
  // The server only lets the test begin once a real recording has reached it.
  await expect(page).toHaveURL(/\/test/, { timeout: 45_000 })

  // ---- the questions
  const header = page.locator('.count')
  await expect(header).toContainText('Question 1 of')
  const total = Number((await header.textContent())?.match(/of (\d+)/)?.[1])
  expect(total).toBeGreaterThan(1)

  for (let position = 1; position <= total; position++) {
    await expect(header).toContainText(`Question ${position} of`)

    if (position === 3) {
      // things a person would do, so the log has something to show
      await page.waitForTimeout(500) // the question fades in; wait for it to be the one that stays
      await page.evaluate(() => window.dispatchEvent(new Event('blur')))
      await page.evaluate(() => window.dispatchEvent(new Event('focus')))
      await page.locator('#question-text').selectText()
      await page.evaluate(() => document.dispatchEvent(new Event('copy')))
      await page.locator('#question-text').click({ button: 'right' })
      // the server saw a copy and a loss of focus, so the page says they were recorded: a calm line
      // that appears over the question and goes by itself
      await expect(page.getByText(FLAG_NOTICE)).toBeVisible({ timeout: 10_000 })
      await page.waitForTimeout(22_000) // long enough for two heartbeats and a chunk or two
    }

    if (position === 4) {
      // the page is reloaded mid-test: the same question comes back, and the camera is asked for again
      await page.reload()
      await expect(header).toContainText('Question 4 of')
      // a reload always leaves full screen, and a page may only re-enter it on a click, so the
      // question is covered until the candidate presses the button (the clock keeps running)
      await page.getByRole('button', { name: 'Return to full screen' }).click()
      await expect(page.getByRole('dialog')).toBeHidden()
      await page.waitForTimeout(4_000)
    }

    if (position === 7) {
      // the connection goes for a while; the test carries on and nothing is lost
      await context.setOffline(true)
      await page.waitForTimeout(OFFLINE_FOR_MS)
      await context.setOffline(false)
    }

    if (position === SKIPPED) {
      await page.getByRole('button', { name: 'Skip' }).click()
    } else {
      await page.locator('label.option').first().click()
      await page.getByRole('button', { name: 'Submit' }).click()
    }
  }

  // ---- the end, the self-report, and the upload to the last chunk
  await expect(page).toHaveURL(/\/done/, { timeout: 30_000 })
  await expect(page.getByText('Test finished')).toBeVisible()
  await page.getByText('No', { exact: true }).click()
  await page.getByRole('button', { name: 'Send' }).click()

  await expect(page).toHaveURL(/\/uploading/)
  await expect(page.getByText(UPLOAD_DONE)).toBeVisible({ timeout: 90_000 })
  await page.getByRole('button', { name: 'Finish', exact: true }).click()
  await expect(page.getByText(FINISHED_TITLE)).toBeVisible()

  // ---- the recording is safe, so the candidate is told how to leave full screen, and can
  await expect(page.getByText(FLAG_NOTICE)).toBeHidden() // it was only for the test
  expect(await page.evaluate(() => document.fullscreenElement !== null)).toBe(true)
  await expect(page.getByText(FINISHED_LEAVE)).toBeVisible()
  await page.getByRole('button', { name: FINISHED_LEAVE_BUTTON }).click()
  await expect(page.getByText(FINISHED_LEAVE)).toBeHidden()
  expect(await page.evaluate(() => document.fullscreenElement === null)).toBe(true)
})
