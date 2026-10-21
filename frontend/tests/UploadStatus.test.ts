import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import UploadStatus from '../src/candidate/UploadStatus.vue'
import {
  FINISHED_TITLE,
  UPLOAD_CLOSED,
  UPLOAD_DONE,
  UPLOAD_RESUME_HINT,
  UPLOAD_STUCK,
} from '../src/candidate/copy'
import { api } from '../src/lib/api'
import { flushEvents, logEvent, startEventLog } from '../src/lib/eventLog'
import { resetMock, setMockLatency } from '../src/lib/mock'
import { clearSession, saveSession } from '../src/lib/session'
import { startUploader } from '../src/lib/uploader'
import type { UploadStatus as LocalUpload } from '../src/lib/uploader'
import { mountPage, settle } from './helpers/render'

vi.mock('../src/lib/api', async (importOriginal) =>
  (await import('./helpers/mockedApi')).withMockedApi(await importOriginal()),
)
vi.mock('../src/lib/eventLog', () => ({
  startEventLog: vi.fn(),
  logEvent: vi.fn(() => Promise.resolve()),
  flushEvents: vi.fn(async () => true),
}))

// What this computer still holds, as the uploader would report it, under the test's control
const EMPTY: LocalUpload = { total: 0, pending: 0, done: 0, failed: 0, bytesPending: 0, halted: null, retrying: false }
const up = vi.hoisted(() => ({
  status: null as unknown as LocalUpload,
  listeners: new Set<(status: LocalUpload) => void>(),
}))
vi.mock('../src/lib/uploader', () => ({
  startUploader: vi.fn(),
  uploadStatus: () => up.status,
  onUploadStatus: (listener: (status: LocalUpload) => void) => {
    up.listeners.add(listener)
    return () => up.listeners.delete(listener)
  },
}))
const setLocal = (patch: Partial<LocalUpload>) => {
  up.status = { ...up.status, ...patch }
  up.listeners.forEach((listener) => listener(up.status))
}

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
    up.status = { ...EMPTY }
    up.listeners.clear()
    vi.mocked(startUploader).mockClear()
    vi.mocked(startEventLog).mockClear()
    vi.mocked(logEvent).mockClear()
    vi.mocked(flushEvents).mockClear()
  })

  afterEach(() => {
    document.body.innerHTML = ''
    clearSession()
    vi.useRealTimers()
    vi.mocked(api).mockReset()
  })

  it('sends what this computer still holds, for this session, as soon as it opens', async () => {
    await renderPage()
    await wait(0)
    expect(startEventLog).toHaveBeenCalledWith('s1')
    expect(startUploader).toHaveBeenCalledWith('s1')
  })

  it('says how many parts are still on this computer, and why they have not gone', async () => {
    const w = await renderPage()
    await wait(0)
    expect(w.text()).not.toContain('still on this computer')

    setLocal({ pending: 3 })
    await wait(0)
    expect(w.text()).toContain('3 parts are still on this computer')

    setLocal({ pending: 1, retrying: true })
    await wait(0)
    expect(w.text()).toContain('1 part is still on this computer')
    expect(w.text()).toContain('waiting for the connection')
  })

  it('tells a candidate who may close the tab how to come back and finish', async () => {
    const w = await renderPage()
    await wait(0)
    expect(w.text()).toContain(UPLOAD_RESUME_HINT)

    await wait(3000 * 6) // everything uploaded
    expect(w.text()).not.toContain(UPLOAD_RESUME_HINT)
  })

  it('offers to finish anyway, and says why, once the time for sending has passed', async () => {
    const w = await renderPage()
    await wait(0)
    expect(hasButton(w, 'Finish anyway')).toBe(false)

    setLocal({ halted: 'closed' })
    await wait(0)
    expect(w.text()).toContain(UPLOAD_CLOSED)
    expect(hasButton(w, 'Finish anyway')).toBe(true)
  })

  it('tells the server how much was missing when the candidate finishes anyway', async () => {
    const w = await renderPage()
    await wait(0) // the first manifest: 9 of 42, so 33 missing
    setLocal({ halted: 'closed' })
    await wait(0)

    await press(w, 'Finish anyway')

    expect(logEvent).toHaveBeenCalledWith('upload_incomplete', { missing: 33 })
    expect(flushEvents).toHaveBeenCalled()
    expect(w.text()).toContain(FINISHED_TITLE)
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
