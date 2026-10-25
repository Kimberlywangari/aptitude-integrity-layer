import { expect, test } from '@playwright/test'
import { EMAIL, PASSWORD, signInAsAdmin } from './admin'

// The staff side of results, in a real browser: the outcomes list, passing several people at once,
// failing one after a review, the pass mark on a closed sitting, the download, and uploading a
// list as a PDF, RTF or HTML file.
//
// It needs a scratch database (it sends results, which queue real rows) holding the made-up
// cohort with addresses that cannot receive mail, and an admin account:
//
//   python -m scripts.jobs simulate_cohort --with-emails
//   E2E_ADMIN_EMAIL, E2E_ADMIN_PASSWORD   the admin
//   E2E_COHORT                            the sitting's name (default below)
//
// Start the API with a mail server that is not there (see the README) so nothing can be sent.
// It sends results and sets a pass mark, so it works once per cohort: purge and make the cohort
// again (`simulate_cohort --purge`, then `simulate_cohort --with-emails`) before running it again.

const COHORT = process.env.E2E_COHORT ?? 'Simulated cohort 1 (made up)'
const QUESTIONS = 12

/** A one-page PDF with a line of text, built by hand: no library, no file to keep. */
function pdfWith(text: string): Buffer {
  const content = `BT /F1 12 Tf 72 720 Td (${text}) Tj ET`
  const objects = [
    '<< /Type /Catalog /Pages 2 0 R >>',
    '<< /Type /Pages /Kids [3 0 R] /Count 1 >>',
    '<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>',
    `<< /Length ${content.length} >>\nstream\n${content}\nendstream`,
    '<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>',
  ]
  let out = '%PDF-1.4\n'
  const offsets: number[] = []
  objects.forEach((body, index) => {
    offsets.push(out.length)
    out += `${index + 1} 0 obj\n${body}\nendobj\n`
  })
  const xref = out.length
  out += `xref\n0 ${objects.length + 1}\n0000000000 65535 f \n`
  out += offsets.map((offset) => `${String(offset).padStart(10, '0')} 00000 n \n`).join('')
  out += `trailer\n<< /Size ${objects.length + 1} /Root 1 0 R >>\nstartxref\n${xref}\n%%EOF\n`
  return Buffer.from(out, 'latin1')
}

test('the outcomes list: pass several at once, fail one after a review, set the pass mark, download', async ({
  browser,
}) => {
  test.skip(!EMAIL || !PASSWORD, 'set E2E_ADMIN_EMAIL and E2E_ADMIN_PASSWORD')
  const admin = await (await browser.newContext()).newPage()
  await signInAsAdmin(admin)

  // ---- everyone, by where they stand
  await admin.goto('/outcomes')
  await admin.locator('#sitting').selectOption({ label: COHORT })
  await expect(admin.locator('#outcomes-heading')).toHaveText('16 invited')
  await expect(admin.locator('tbody tr')).toHaveCount(16)
  // an admin sees names, with the address half hidden
  await expect(admin.locator('tbody tr').first()).toContainText('Simulated Person')
  await expect(admin.locator('tbody tr').first()).toContainText('***@example.invalid')

  // ---- the people who can be passed are passed in one go, after one confirmation
  await admin.getByLabel('Select everyone who can be passed').check()
  const bulk = admin.getByRole('button', { name: /^Mark \d+ selected as passed and send emails$/ })
  const howMany = Number((await bulk.textContent())?.match(/Mark (\d+)/)?.[1])
  expect(howMany).toBeGreaterThan(0)
  await bulk.click()
  await expect(admin.getByText(/Pass \d+ candidates? and send each their pass email now\?/)).toBeVisible()
  await admin.getByRole('button', { name: 'Yes, pass and send' }).click()
  await expect(admin.getByText(new RegExp(`${howMany} pass emails? (is|are) on the way`))).toBeVisible({
    timeout: 20_000,
  })
  await expect(admin.getByRole('button', { name: `Passed ${howMany}` })).toBeVisible()

  // ---- a flagged candidate: held until a decision is recorded, then turned down with a reason
  await admin.getByRole('button', { name: /^Waiting for review/ }).click()
  await expect(admin.locator('tbody tr').first()).toContainText('Waiting for review')
  await admin.locator('tbody tr').first().locator('a').first().click()
  await expect(admin.locator('#result-heading')).toBeVisible()
  await expect(admin.getByText('This candidate is flagged. Record your decision above first')).toBeVisible()
  await expect(admin.getByRole('button', { name: 'Send result email' })).toHaveCount(0)

  await admin.getByText('No concern', { exact: true }).click()
  await admin.locator('#reason').fill('Looked at the record: nothing here changes the result.')
  await admin.getByText('I have looked at the evidence and this reason is mine.').click()
  await admin.getByRole('button', { name: 'Record decision' }).click()
  await expect(admin.getByText('Decision recorded.')).toBeVisible()

  await admin.getByText('Do not pass', { exact: true }).click()
  await admin.locator('#result-reason').selectOption('copy')
  await admin.getByRole('button', { name: 'Send result email' }).click()
  await expect(admin.getByText('Send the not-passed email now? It cannot be taken back.')).toBeVisible()
  await admin.getByRole('button', { name: 'Yes, send' }).click()
  await expect(admin.getByText(/Did not pass, decided by/)).toBeVisible({ timeout: 20_000 })
  await expect(admin.getByText(/Reason given: The record shows attempts to copy/)).toBeVisible()
  // it cannot be sent twice
  await expect(admin.getByRole('button', { name: 'Send result email' })).toHaveCount(0)
  // and only an admin can note an appeal
  await admin.getByRole('button', { name: 'Mark as under appeal' }).click()
  await expect(admin.getByRole('button', { name: 'Appeal closed' })).toBeVisible()

  // ---- the pass mark of a closed sitting: previewed first, then the rejections go
  await admin.goto('/admin')
  await admin.locator('tbody tr', { hasText: COHORT }).locator('td').nth(1).click()
  await expect(admin.locator('#pass-mark-heading')).toBeVisible()
  await expect(admin.getByText('Now: not set')).toBeVisible()
  await admin.locator('#pass-mark').fill(String(QUESTIONS + 1))
  await expect(admin.getByText(`Use a whole number from 1 to ${QUESTIONS}`)).toBeVisible()
  await admin.locator('#pass-mark').fill(String(QUESTIONS))
  await admin.getByRole('button', { name: 'See what it would change' }).click()
  await expect(admin.getByText(/would be below the mark/)).toBeVisible()
  await expect(admin.getByText(/This sitting is closed, so \d+ rejection emails? go(es)? out now/)).toBeVisible()
  await expect(admin.getByText('Now: not set')).toBeVisible() // previewing changed nothing
  await admin.getByRole('button', { name: `Set the pass mark to ${QUESTIONS}` }).click()
  await expect(admin.getByText(`The pass mark is ${QUESTIONS}.`)).toBeVisible({ timeout: 20_000 })
  await expect(admin.getByText(`Now: ${QUESTIONS} of ${QUESTIONS}`)).toBeVisible()

  await admin.goto('/outcomes')
  await admin.locator('#sitting').selectOption({ label: COHORT })
  await expect(admin.getByText(`Pass mark: ${QUESTIONS} of ${QUESTIONS} correct.`)).toBeVisible()
  await expect(admin.getByRole('button', { name: /^Below pass mark [1-9]/ })).toBeVisible()
  // the one the admin passed by hand and the one turned down after review are not touched
  await expect(admin.getByRole('button', { name: `Passed ${howMany}` })).toBeVisible()

  // ---- the list can be downloaded, and has the names the reviewers' copy does not
  const [download] = await Promise.all([
    admin.waitForEvent('download'),
    admin.getByRole('button', { name: 'Download as CSV' }).click(),
  ])
  const chunks: Buffer[] = []
  for await (const chunk of await download.createReadStream()) chunks.push(chunk as Buffer)
  const csv = Buffer.concat(chunks).toString('utf8')
  expect(csv.split(/\r?\n/)[0]).toBe('candidate_id,name,email,status,score,of,flags,email_state')
  expect(csv).toContain('Simulated Person')
  expect(csv).toContain('@example.invalid')
})

test('a list can be uploaded as a PDF, a Word-style RTF, HTML or plain text, and says why a file will not do', async ({
  browser,
}) => {
  test.skip(!EMAIL || !PASSWORD, 'set E2E_ADMIN_EMAIL and E2E_ADMIN_PASSWORD')
  const admin = await (await browser.newContext()).newPage()
  await signInAsAdmin(admin)
  await admin.goto('/admin/invites')
  await admin.locator('#people').waitFor()
  const choose = admin.locator('input[aria-label="Upload a list"]')
  const box = admin.locator('#people')

  // no list of allowed types: a file of any kind can be picked, and the server says if it can read it
  expect(await choose.getAttribute('accept')).toBeNull()

  await choose.setInputFiles({
    name: 'people.rtf',
    mimeType: 'application/rtf',
    buffer: Buffer.from(String.raw`{\rtf1\ansi Ada Lovelace, ada@example.org\par Grace Hopper, grace@navy.test\par}`),
  })
  await expect(box).toHaveValue(/Ada Lovelace, ada@example\.org\s+Grace Hopper, grace@navy\.test/)

  await choose.setInputFiles({
    name: 'people.html',
    mimeType: 'text/html',
    buffer: Buffer.from('<html><body><p>Katherine Johnson, katherine@nasa.test</p></body></html>'),
  })
  await expect(box).toHaveValue('Katherine Johnson, katherine@nasa.test')

  await choose.setInputFiles({
    name: 'people.pdf',
    mimeType: 'application/pdf',
    buffer: pdfWith('Margaret Hamilton, margaret@mit.test'),
  })
  await expect(box).toHaveValue(/Margaret Hamilton, margaret@mit\.test/)

  // the name means nothing: a PDF called .txt is still read as a PDF
  await choose.setInputFiles({
    name: 'people.txt',
    mimeType: 'text/plain',
    buffer: pdfWith('Radia Perlman, radia@mit.test'),
  })
  await expect(box).toHaveValue(/Radia Perlman, radia@mit\.test/)

  // an old binary Word file, and a PDF made only of pictures, are turned away in plain words
  await choose.setInputFiles({
    name: 'people.doc',
    mimeType: 'application/msword',
    buffer: Buffer.concat([Buffer.from('D0CF11E0A1B11AE1', 'hex'), Buffer.alloc(600)]),
  })
  await expect(admin.getByText(/old Word, Excel or PowerPoint file/)).toBeVisible()
  await choose.setInputFiles({
    name: 'scan.pdf',
    mimeType: 'application/pdf',
    buffer: pdfWith(''),
  })
  await expect(admin.getByText(/pictures of pages/)).toBeVisible()
  // the list the last good file put in the box was left alone
  await expect(box).toHaveValue(/Radia Perlman/)
})
