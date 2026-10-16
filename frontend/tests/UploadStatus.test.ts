import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import UploadStatus from '../src/candidate/UploadStatus.vue'
import { FINISHED_TITLE, UPLOAD_DONE, UPLOAD_STUCK } from '../src/candidate/copy'
import { api } from '../src/lib/api'
import { resetMock, setMockLatency } from '../src/lib/mock'
import { clearSession, saveSession } from '../src/lib/session'
import { mountPage, settle } from './helpers/render'

vi.mock('../src/lib/api', async (importOriginal) =>
  (await import('./helpers/mockedApi')).withMockedApi(await importOriginal()),
)

const wait = (ms: number) => settle((n) => vi.advanceTimersByTimeAsync(n), ms)

async function renderPage() {
  const { wrapper } = await mountPage('/uploading', { '/uploading': UploadStatus, '/candidate': 'start page' })
  return wrapper
}

type Page = Awaited<ReturnType<typeof renderPage>>
const hasButton = (w: Page, name: string) => w.findAll('button').some((b) => b.text().trim() === name)
const press = async (w: Page, name: string) => {
  await w.findAll('button').find((b) => b.text().trim() === name)!.trigger('click')
  await wait(0)
}

describe('UploadStatus', () => {
  beforeEach(() => {
    vi.useFakeTimers()
    setMockLatency(0)
    resetMock()
    saveSession('s1', 'tok')
  })

  afterEach(() => {
    document.body.innerHTML = ''
    clearSession()
    vi.useRealTimers()
    vi.mocked(api).mockReset()
  })

  it('shows progress, then offers Finish once everything is uploaded', async () => {
    const w = await renderPage()
    await wait(0)
    expect(w.text()).toMatch(/Uploaded 9 of 42 parts/)
    expect(hasButton(w, 'Finish')).toBe(false)

    await wait(3000 * 4) // four more polls take the mock manifest to 42 of 42
    expect(w.text()).toContain(UPLOAD_DONE)
    expect(hasButton(w, 'Finish')).toBe(true)
    expect(hasButton(w, 'Finish anyway')).toBe(false)
  })

  it('stops polling once the upload is complete', async () => {
    await renderPage()
    await wait(3000 * 6)
    const calls = vi.mocked(api).mock.calls.length
    await wait(3000 * 5)
    expect(vi.mocked(api).mock.calls.length).toBe(calls)
  })

  it('ends on a plain thank-you once the candidate presses Finish', async () => {
    const w = await renderPage()
    await wait(3000 * 6)
    await press(w, 'Finish')
    expect(w.text()).toContain(FINISHED_TITLE)
    expect(w.text()).toContain('You can close this window')
  })

  it('offers Finish anyway after repeated failures, never before', async () => {
    vi.mocked(api).mockRejectedValue(new Error('offline'))
    const w = await renderPage()
    await wait(0)
    expect(hasButton(w, 'Finish anyway')).toBe(false)

    await wait(3000 * 3)
    expect(w.text()).toContain(UPLOAD_STUCK)
    expect(hasButton(w, 'Finish anyway')).toBe(true)
    expect(hasButton(w, 'Finish')).toBe(false)
  })

  it('asks before the tab is closed while parts are still unsent, but not once it is done', async () => {
    await renderPage()
    await wait(0)
    const early = new Event('beforeunload', { cancelable: true })
    window.dispatchEvent(early)
    expect(early.defaultPrevented).toBe(true)

    await wait(3000 * 6)
    const late = new Event('beforeunload', { cancelable: true })
    window.dispatchEvent(late)
    expect(late.defaultPrevented).toBe(false)
  })
})
