import { flushPromises } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import Done from '../src/candidate/Done.vue'
import { api, ApiError } from '../src/lib/api'
import { stopRecording } from '../src/lib/recording'
import { endTestRuntime } from '../src/lib/runtime'
import { clearSession, saveSession } from '../src/lib/session'
import { mountPage } from './helpers/render'

vi.mock('../src/lib/api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../src/lib/api')>()
  return { ...actual, api: vi.fn() }
})
vi.mock('../src/lib/recording', () => ({ stopRecording: vi.fn() }))
vi.mock('../src/lib/runtime', () => ({ endTestRuntime: vi.fn(async () => undefined) }))

const summary = { status: 'finished', total: 12, answered: 10, skipped: 2, unanswered: 0 }

async function renderPage() {
  const { wrapper } = await mountPage('/done', {
    '/done': Done,
    '/uploading': 'uploading page',
    '/candidate': 'start page',
    '/test': 'test page',
  })
  await flushPromises()
  return wrapper
}

const finishCall = () =>
  vi.mocked(api).mock.calls.find((call) => String(call[0]).endsWith('/finish')) as
    | [string, { method: string; body?: { chunks_total: number } }]
    | undefined

describe('Done (the end of the test)', () => {
  beforeEach(() => {
    saveSession('s1', 'tok')
    vi.mocked(api).mockReset()
    vi.mocked(api).mockResolvedValue(summary)
    vi.mocked(stopRecording).mockReset()
    vi.mocked(stopRecording).mockResolvedValue(42)
    vi.mocked(endTestRuntime).mockClear()
  })

  afterEach(() => {
    document.body.innerHTML = ''
    clearSession()
  })

  it('goes back to the start page when there is no session', async () => {
    clearSession()
    const w = await renderPage()
    expect(w.text()).toContain('start page')
    expect(stopRecording).not.toHaveBeenCalled()
  })

  it('stops the recording first, so the last chunk is counted, and tells the server how many there were', async () => {
    await renderPage()

    expect(finishCall()?.[0]).toBe('/api/session/s1/finish')
    expect(finishCall()?.[1]).toMatchObject({ method: 'POST', body: { chunks_total: 42 } })
    expect(vi.mocked(stopRecording).mock.invocationCallOrder[0]).toBeLessThan(
      vi.mocked(api).mock.invocationCallOrder[0],
    )
  })

  it('leaves the total out when nothing was recorded, rather than saying none are expected', async () => {
    vi.mocked(stopRecording).mockResolvedValue(0)
    await renderPage()
    expect(finishCall()?.[1].body).toBeUndefined()
  })

  it('ends the background work only after finishing, so the closing events are sent', async () => {
    await renderPage()
    expect(endTestRuntime).toHaveBeenCalledTimes(1)
    expect(vi.mocked(endTestRuntime).mock.invocationCallOrder[0]).toBeGreaterThan(
      vi.mocked(api).mock.invocationCallOrder[0],
    )
  })

  it('says how many questions were answered', async () => {
    const w = await renderPage()
    expect(w.text()).toContain('You answered 10 of 12 questions.')
  })

  it('still ends the background work, and leaves, when the server refuses the finish', async () => {
    vi.mocked(api).mockRejectedValue(new ApiError(401, 'unauthorized', {}))
    const w = await renderPage()
    expect(w.text()).toContain('start page')
    expect(endTestRuntime).toHaveBeenCalled()
  })

  it('goes on to the upload page after the self-report', async () => {
    const w = await renderPage()
    await w.findAll('input[name=issues]')[0].setValue(true)
    await w.get('form').trigger('submit')
    await flushPromises()

    const report = vi.mocked(api).mock.calls.find((call) => String(call[0]).endsWith('/self-report'))
    expect(report?.[1]).toMatchObject({ method: 'POST', body: { had_technical_issues: false, note: null } })
    expect(w.text()).toContain('uploading page')
  })
})
