import { flushPromises } from '@vue/test-utils'
import type { VueWrapper } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { resetMock, setMockLatency } from './mock'
import { clearStaff, saveStaff } from '../src/lib/staffSession'
import { clearQueryClient } from '../src/staff/queryClient'
import { renderApp, until } from './helpers/render'

vi.mock('../src/lib/api', async (importOriginal) =>
  (await import('./helpers/mockedApi')).withMockedApi(await importOriginal()),
)

async function renderAt(path: string) {
  const { wrapper } = await renderApp(path)
  await flushPromises()
  return wrapper
}

const norm = (text: string) => text.replace(/\s+/g, ' ').trim()
const untilText = (w: VueWrapper, re: RegExp | string) =>
  until(() => (typeof re === 'string' ? norm(w.text()).includes(re) : re.test(norm(w.text()))))
const button = (w: VueWrapper, name: string | RegExp) =>
  w
    .findAll('button')
    .find((b) => (typeof name === 'string' ? norm(b.text()) === name : name.test(norm(b.text()))))
const rows = (w: VueWrapper) => w.findAll('tbody tr')
const rowOf = (w: VueWrapper, id: string) => rows(w).find((r) => r.text().includes(id))!

const asReviewer = () =>
  saveStaff({ token: 'mock-reviewer:r@example.com', email: 'r@example.com', role: 'reviewer' })
const asAdmin = () =>
  saveStaff({ token: 'mock-admin:admin@example.com', email: 'admin@example.com', role: 'admin' })

beforeEach(() => {
  setMockLatency(0)
  resetMock()
  clearStaff()
  clearQueryClient()
})

afterEach(() => {
  clearStaff()
  clearQueryClient()
  document.body.innerHTML = ''
})

describe('the result panel on a candidate page', () => {
  beforeEach(asReviewer)

  it('holds a flagged candidate back until a decision is recorded, and says why', async () => {
    const w = await renderAt('/review/candidates/cand-007')
    await untilText(w, 'Result and email')
    expect(w.text()).toContain('Waiting for review')
    expect(norm(w.text())).toContain('This candidate is flagged. Record your decision above first')
    expect(button(w, 'Send result email')).toBeUndefined()
  })

  it('shows the score and says when no pass mark is set', async () => {
    const w = await renderAt('/review/candidates/cand-001')
    await untilText(w, 'Result and email')
    expect(norm(w.text())).toContain('Score 5 of 12 · no pass mark set for this sitting')
  })

  it('asks before it sends, and a pass goes once it is confirmed', async () => {
    const w = await renderAt('/review/candidates/cand-018')
    await untilText(w, 'Result and email')
    const send = button(w, 'Send result email')!
    expect((send.element as HTMLButtonElement).disabled).toBe(true) // nothing chosen yet

    await w.get('input[name=result][value=pass]').setValue(true)
    expect((button(w, 'Send result email')!.element as HTMLButtonElement).disabled).toBe(false)
    await button(w, 'Send result email')!.trigger('click')
    expect(norm(w.text())).toContain('Send the pass email now? It cannot be taken back.')

    await button(w, 'Yes, send')!.trigger('click')
    await untilText(w, 'Passed, decided by r@example.com')
    expect(norm(w.text())).toContain('Email: Sending')
    expect(button(w, 'Send result email')).toBeUndefined() // it cannot be sent twice
  })

  it('sends nothing when the question is cancelled', async () => {
    const w = await renderAt('/review/candidates/cand-018')
    await untilText(w, 'Result and email')
    await w.get('input[name=result][value=pass]').setValue(true)
    await button(w, 'Send result email')!.trigger('click')
    await button(w, 'Cancel')!.trigger('click')
    expect(button(w, 'Send result email')).toBeDefined()
    expect(w.text()).not.toContain('Passed, decided by')
  })

  it('needs a reason before a candidate is turned down, and passes the chosen one on', async () => {
    const w = await renderAt('/review/candidates/cand-018')
    await untilText(w, 'Result and email')
    await w.get('input[name=result][value=fail]').setValue(true)
    expect((button(w, 'Send result email')!.element as HTMLButtonElement).disabled).toBe(true)

    await w.get('#result-reason').setValue('copy')
    expect((button(w, 'Send result email')!.element as HTMLButtonElement).disabled).toBe(false)
    await button(w, 'Send result email')!.trigger('click')
    await button(w, 'Yes, send')!.trigger('click')
    await untilText(w, 'Did not pass, decided by r@example.com')
    expect(norm(w.text())).toContain('Reason given: The record shows attempts to copy from')
  })

  it('takes a reviewer’s own line, and will not send an empty one', async () => {
    const w = await renderAt('/review/candidates/cand-018')
    await untilText(w, 'Result and email')
    await w.get('input[name=result][value=fail]').setValue(true)
    await w.get('#result-reason').setValue('other')
    expect((button(w, 'Send result email')!.element as HTMLButtonElement).disabled).toBe(true)

    await w.get('#result-text').setValue('The recording stopped at 10:40.')
    expect((button(w, 'Send result email')!.element as HTMLButtonElement).disabled).toBe(false)
    await button(w, 'Send result email')!.trigger('click')
    await button(w, 'Yes, send')!.trigger('click')
    await untilText(w, 'Reason given: The recording stopped at 10:40.')
  })

  it('says someone who has not finished has no result to send', async () => {
    const w = await renderAt('/review/candidates/cand-020')
    await untilText(w, 'Result and email')
    expect(norm(w.text())).toContain('has not finished the test, so there is no result to send')
    expect(w.find('input[name=result]').exists()).toBe(false)
  })

  it('lets a reviewer send an unflagged candidate their result at once', async () => {
    const w = await renderAt('/review/candidates/cand-001')
    await untilText(w, 'Result and email')
    expect(w.text()).toContain('Ready for a result')
    await w.get('input[name=result][value=pass]').setValue(true)
    await button(w, 'Send result email')!.trigger('click')
    await button(w, 'Yes, send')!.trigger('click')
    await untilText(w, 'Passed, decided by r@example.com')
  })

  it('offers the appeal note to an admin only', async () => {
    const reviewerView = await renderAt('/review/candidates/cand-018')
    await untilText(reviewerView, 'Result and email')
    await reviewerView.get('input[name=result][value=fail]').setValue(true)
    await reviewerView.get('#result-reason').setValue('focus')
    await button(reviewerView, 'Send result email')!.trigger('click')
    await button(reviewerView, 'Yes, send')!.trigger('click')
    await untilText(reviewerView, 'Did not pass')
    expect(button(reviewerView, 'Mark as under appeal')).toBeUndefined()
    reviewerView.unmount()

    clearStaff()
    clearQueryClient()
    asAdmin()
    const adminView = await renderAt('/review/candidates/cand-018')
    await untilText(adminView, 'Did not pass')
    await button(adminView, 'Mark as under appeal')!.trigger('click')
    await untilText(adminView, 'Under appeal')
    expect(button(adminView, 'Appeal closed')).toBeDefined()
  })
})

describe('the outcomes list', () => {
  it('shows a reviewer every status by candidate ID, with no names and no download', async () => {
    asReviewer()
    const w = await renderAt('/outcomes')
    await untilText(w, 'Outcomes')
    await until(() => rows(w).length === 10)
    expect(w.text()).not.toContain('Person ')
    expect(button(w, 'Download as CSV')).toBeUndefined()
    expect(norm(w.text())).toContain('10 invited')
    expect(norm(w.text())).toContain('Waiting for review 6')
    expect(norm(w.text())).toContain('Reviewed, no result yet 1')
    expect(norm(w.text())).toContain('Ready for a result 1')
    expect(norm(w.text())).toContain('Sitting now 1')
    expect(norm(w.text())).toContain('Not started 1')
  })

  it('lets an admin see names and download the list', async () => {
    asAdmin()
    const w = await renderAt('/outcomes')
    await until(() => rows(w).length === 10)
    expect(rowOf(w, 'cand-001').text()).toContain('Person 001')
    expect(button(w, 'Download as CSV')).toBeDefined()
  })

  it('filters by status and finds a candidate by ID', async () => {
    asReviewer()
    const w = await renderAt('/outcomes')
    await until(() => rows(w).length === 10)

    await button(w, /^Ready for a result/)!.trigger('click')
    await until(() => rows(w).length === 1)
    expect(rows(w)[0].text()).toContain('cand-001')

    await button(w, /^All/)!.trigger('click')
    await until(() => rows(w).length === 10)
    await w.get('#find').setValue('cand-0')
    await w.get('#find').setValue('cand-007')
    await until(() => rows(w).length === 1)
    expect(rows(w)[0].text()).toContain('cand-007')
  })

  it('only lets a person select those who can be passed', async () => {
    asReviewer()
    const w = await renderAt('/outcomes')
    await until(() => rows(w).length === 10)
    const boxOf = (id: string) => rowOf(w, id).get('input[type=checkbox]').element as HTMLInputElement
    expect(boxOf('cand-001').disabled).toBe(false) // ready
    expect(boxOf('cand-018').disabled).toBe(false) // reviewed
    expect(boxOf('cand-007').disabled).toBe(true) // flagged, no decision yet
    expect(boxOf('cand-020').disabled).toBe(true) // still sitting
  })

  it('passes everyone selected after one confirmation', async () => {
    asReviewer()
    const w = await renderAt('/outcomes')
    await until(() => rows(w).length === 10)
    expect(button(w, /^Mark 0 selected/)!.attributes('disabled')).toBeDefined()

    await w.get('thead input[type=checkbox]').setValue(true) // everyone who can be passed
    await until(() => button(w, /^Mark 2 selected as passed/) !== undefined)
    await button(w, /^Mark 2 selected as passed/)!.trigger('click')
    expect(norm(w.text())).toContain('Pass 2 candidates and send each their pass email now?')

    await button(w, 'Yes, pass and send')!.trigger('click')
    await untilText(w, '2 pass emails are on the way.')
    await until(() => rowOf(w, 'cand-001').text().includes('Passed'))
    expect(rowOf(w, 'cand-001').text()).toContain('Sending')
    expect(norm(w.text())).toContain('Passed 2')
  })
})

describe('the pass mark on a sitting', () => {
  beforeEach(asAdmin)

  it('shows what a change would do before it does anything', async () => {
    const w = await renderAt('/admin/sittings/1')
    await untilText(w, 'Now: not set')
    await w.get('#pass-mark').setValue('8')
    await button(w, 'See what it would change')!.trigger('click')
    await untilText(w, '4 candidates would be below the mark')
    expect(norm(w.text())).toContain('This sitting is open, so nothing is sent until you close it.')
    expect(norm(w.text())).toContain('Now: not set') // nothing has changed yet

    await button(w, 'Set the pass mark to 8')!.trigger('click')
    await untilText(w, 'The pass mark is 8.')
    await untilText(w, 'Now: 8 of 12')
  })

  it('can be cancelled at the preview', async () => {
    const w = await renderAt('/admin/sittings/1')
    await untilText(w, 'Now: not set')
    await w.get('#pass-mark').setValue('8')
    await button(w, 'See what it would change')!.trigger('click')
    await untilText(w, 'would be below the mark')
    await button(w, 'Cancel')!.trigger('click')
    expect(button(w, 'Set the pass mark to 8')).toBeUndefined()
    expect(norm(w.text())).toContain('Now: not set')
  })

  it('refuses a mark the sitting cannot have', async () => {
    const w = await renderAt('/admin/sittings/1')
    await untilText(w, 'Now: not set')
    await w.get('#pass-mark').setValue('99')
    expect(norm(w.text())).toContain('Use a whole number from 1 to 12')
    expect((button(w, 'See what it would change')!.element as HTMLButtonElement).disabled).toBe(true)
  })

  it('moves the outcomes list when the mark is set', async () => {
    const w = await renderAt('/admin/sittings/1')
    await untilText(w, 'Now: not set')
    await w.get('#pass-mark').setValue('8')
    await button(w, 'See what it would change')!.trigger('click')
    await untilText(w, 'would be below the mark')
    await button(w, 'Set the pass mark to 8')!.trigger('click')
    await untilText(w, 'The pass mark is 8.')
    w.unmount()

    const list = await renderAt('/outcomes')
    await until(() => rows(list).length === 10)
    expect(norm(list.text())).toContain('Pass mark: 8 of 12 correct.')
    expect(norm(list.text())).toContain('Below pass mark 4')
    expect(rowOf(list, 'cand-003').text()).toContain('Below pass mark') // scored 2
    expect(rowOf(list, 'cand-007').text()).toContain('Waiting for review') // scored 9, over the mark
  })
})

describe('the result emails on a sitting page', () => {
  beforeEach(asAdmin)

  it('counts what has gone and who is waiting, and sends nothing from here', async () => {
    const w = await renderAt('/admin/sittings/1')
    await untilText(w, 'Result emails')
    expect(norm(w.text())).toContain('3 pass emails sent, 1 not-passed email sent')
    expect(norm(w.get('#held-back').text())).toContain('1 finished and waiting for a result: cand-007')
    expect(norm(w.text())).toContain('2 did not finish and get no email')
    expect(button(w, /^Send (pass|not-passed) emails/)).toBeUndefined()
  })

  it('lets an admin read all three emails', async () => {
    const w = await renderAt('/admin/sittings/1')
    await untilText(w, 'Result emails')
    const text = w.get('details').text()
    expect(text).toContain('You passed.')
    expect(text).toContain('Not this time.')
    expect(text).toContain('A person looked at your sitting.')
  })
})
