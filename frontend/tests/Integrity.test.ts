import { flushPromises } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { RECORDING_PROBLEMS, RECORDING_STARTING } from '../src/candidate/copy'
import Integrity from '../src/candidate/Integrity.vue'
import { api, ApiError } from '../src/lib/api'
import { prepareRecording } from '../src/lib/runtime'
import type { PrepareResult } from '../src/lib/runtime'
import { clearSession, saveSession } from '../src/lib/session'
import { mountPage } from './helpers/render'

vi.mock('../src/lib/api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../src/lib/api')>()
  return { ...actual, api: vi.fn() }
})
vi.mock('../src/lib/runtime', () => ({ prepareRecording: vi.fn() }))

const pages = {
  '/integrity': Integrity,
  '/test': 'test page',
  '/precheck': 'precheck page',
  '/done': 'done page',
  '/candidate': 'start page',
}

async function renderPage() {
  const { wrapper, router } = await mountPage('/integrity', pages)
  return { w: wrapper, router }
}

type Page = Awaited<ReturnType<typeof renderPage>>['w']
const start = (w: Page) => w.findAll('button').find((b) => b.text().includes('start the test') || b.text().includes('Starting'))!

async function agreeAndStart(w: Page) {
  await w.get('input[type=checkbox]').setValue(true)
  await start(w).trigger('click')
  await flushPromises()
}

const begun = () => vi.mocked(api).mock.calls.some((call) => String(call[0]).endsWith('/begin'))

describe('Integrity (the page before the test starts)', () => {
  beforeEach(() => {
    saveSession('s1', 'tok')
    vi.mocked(api).mockReset()
    vi.mocked(api).mockResolvedValue({ status: 'in_progress', remaining_s: 1800 })
    vi.mocked(prepareRecording).mockReset()
    vi.mocked(prepareRecording).mockResolvedValue('ready')
  })

  afterEach(() => {
    document.body.innerHTML = ''
    clearSession()
  })

  it('goes back to the start page when there is no session', async () => {
    clearSession()
    const { w } = await renderPage()
    await flushPromises()
    expect(w.text()).toContain('start page')
  })

  it('cannot start until the statement is agreed', async () => {
    const { w } = await renderPage()
    expect((start(w).element as HTMLButtonElement).disabled).toBe(true)
    expect(prepareRecording).not.toHaveBeenCalled()
  })

  it('starts the recording first, and only then the clock', async () => {
    const { w } = await renderPage()
    await agreeAndStart(w)

    expect(prepareRecording).toHaveBeenCalledWith('s1')
    const [beginCall] = vi.mocked(api).mock.calls.filter((call) => String(call[0]).endsWith('/begin'))
    expect(beginCall[0]).toBe('/api/session/s1/begin')
    expect(beginCall[1]).toMatchObject({ method: 'POST', body: { accepted: true } })
    expect(vi.mocked(prepareRecording).mock.invocationCallOrder[0]).toBeLessThan(
      vi.mocked(api).mock.invocationCallOrder[0],
    )
    expect(w.text()).toContain('test page')
  })

  it('says the recording is starting while it waits, and starts no clock meanwhile', async () => {
    let finish: (result: PrepareResult) => void = () => undefined
    vi.mocked(prepareRecording).mockReturnValue(new Promise((resolve) => (finish = resolve)))
    const { w } = await renderPage()
    await agreeAndStart(w)

    expect(w.text()).toContain(RECORDING_STARTING)
    expect(begun()).toBe(false)

    finish('ready')
    await flushPromises()
    expect(begun()).toBe(true)
  })

  describe.each(['no_devices', 'unsupported', 'slow'] as const)('when the recording is not ready (%s)', (why) => {
    beforeEach(() => vi.mocked(prepareRecording).mockResolvedValue(why))

    it('says what is wrong and what to do, and does not start the clock', async () => {
      const { w } = await renderPage()
      await agreeAndStart(w)

      expect(w.get('[role=alert]').text()).toContain(RECORDING_PROBLEMS[why])
      expect(RECORDING_PROBLEMS[why]).toContain('Your time has not started')
      expect(begun()).toBe(false)
      expect(w.text()).not.toContain('test page')
    })

    it('lets the candidate try again', async () => {
      const { w } = await renderPage()
      await agreeAndStart(w)
      expect((start(w).element as HTMLButtonElement).disabled).toBe(false)

      vi.mocked(prepareRecording).mockResolvedValue('ready')
      await start(w).trigger('click')
      await flushPromises()
      expect(w.text()).toContain('test page')
    })
  })

  describe('when the server will not start the test', () => {
    it('stays here, and says so, when only the recording is missing (the camera check cannot fix that)', async () => {
      vi.mocked(api).mockRejectedValue(new ApiError(409, 'precheck_required', { reason: 'recording' }))
      const { w } = await renderPage()
      await agreeAndStart(w)

      expect(w.get('[role=alert]').text()).toContain(RECORDING_PROBLEMS.not_confirmed)
      expect(w.text()).not.toContain('precheck page')
    })

    it('sends a candidate back to the check when the check itself is missing', async () => {
      vi.mocked(api).mockRejectedValue(new ApiError(409, 'precheck_required', { reason: 'precheck' }))
      const { w } = await renderPage()
      await agreeAndStart(w)
      expect(w.text()).toContain('precheck page')
    })

    it('sends a candidate whose test is already over to the end', async () => {
      vi.mocked(api).mockRejectedValue(new ApiError(409, 'finished', {}))
      const { w } = await renderPage()
      await agreeAndStart(w)
      expect(w.text()).toContain('done page')
    })

    it('says something plain for anything else, and allows another try', async () => {
      vi.mocked(api).mockRejectedValue(new Error('boom'))
      const { w } = await renderPage()
      await agreeAndStart(w)
      expect(w.get('[role=alert]').text()).toContain('Something went wrong')
      expect((start(w).element as HTMLButtonElement).disabled).toBe(false)
    })
  })
})
