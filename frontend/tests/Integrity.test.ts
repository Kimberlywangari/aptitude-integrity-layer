import { flushPromises } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import {
  PAPER_FAILED,
  PAPER_PREPARING,
  PAPER_SLOW,
  PAPER_SLOW_RETRY,
  RECORDING_PROBLEMS,
  RECORDING_STARTING,
} from '../src/candidate/copy'
import Integrity from '../src/candidate/Integrity.vue'
import { api, ApiError } from '../src/lib/api'
import type { PaperResponse } from '../src/lib/api'
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
    const beginAt = vi
      .mocked(api)
      .mock.calls.findIndex((call) => String(call[0]).endsWith('/begin'))
    expect(vi.mocked(prepareRecording).mock.invocationCallOrder[0]).toBeLessThan(
      vi.mocked(api).mock.invocationCallOrder[beginAt],
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

  describe('when an AI sitting is still writing the candidate\'s questions', () => {
    afterEach(() => vi.useRealTimers())

    function paperReplies(...replies: Partial<PaperResponse>[]) {
      const asked: string[] = []
      vi.mocked(api).mockImplementation((async (path: string, options?: { method?: string }) => {
        asked.push(`${options?.method ?? 'GET'} ${path}`)
        if (path.includes('/paper')) {
          const next = replies.length > 1 ? replies.shift() : replies[0]
          return { status: 'ready', written: 12, total: 12, ...next }
        }
        return { status: 'in_progress', remaining_s: 1800 }
      }) as never)
      return asked
    }

    it('shows how far it has got, keeps the start button shut, and opens it when ready', async () => {
      vi.useFakeTimers({ toFake: ['setTimeout', 'clearTimeout'] })
      paperReplies(
        { status: 'pending', written: 1, total: 3 },
        { status: 'pending', written: 2, total: 3 },
        { status: 'ready', written: 3, total: 3 },
      )
      const { w } = await renderPage()
      await flushPromises()
      await w.get('input[type=checkbox]').setValue(true)

      expect(w.text()).toContain(`${PAPER_PREPARING}: 1 of 3 ready`)
      expect(w.text()).toContain('Your time has not started')
      expect((start(w).element as HTMLButtonElement).disabled).toBe(true)

      await vi.advanceTimersByTimeAsync(2000)
      await flushPromises()
      expect(w.text()).toContain(`${PAPER_PREPARING}: 2 of 3 ready`)

      await vi.advanceTimersByTimeAsync(2000)
      await flushPromises()
      expect(w.text()).not.toContain(PAPER_PREPARING)
      expect((start(w).element as HTMLButtonElement).disabled).toBe(false)
    })

    it("says whose test it is, from the candidate's own paper reply", async () => {
      paperReplies({ status: 'ready', candidate_name: 'Ada Lovelace' })
      const { w } = await renderPage()
      await flushPromises()
      expect(w.get('#whose-test').text()).toContain('You are taking this test as Ada Lovelace')
      expect(w.get('#whose-test').text()).toContain('If that is not you, stop here')
    })

    it('says nothing about a name when the candidate has none', async () => {
      paperReplies({ status: 'ready', candidate_name: null })
      const { w } = await renderPage()
      await flushPromises()
      expect(w.find('#whose-test').exists()).toBe(false)
    })

    it('asks once and shows no wait at all for a paper that is already built', async () => {
      const asked = paperReplies({ status: 'ready' })
      const { w } = await renderPage()
      await flushPromises()
      await w.get('input[type=checkbox]').setValue(true)

      expect(w.text()).not.toContain(PAPER_PREPARING)
      expect((start(w).element as HTMLButtonElement).disabled).toBe(false)
      expect(asked).toEqual(['GET /api/session/s1/paper'])
    })

    it('says so when the questions could not be written, and lets the candidate try again', async () => {
      vi.useFakeTimers({ toFake: ['setTimeout', 'clearTimeout'] })
      const asked = paperReplies({ status: 'failed', written: 1, total: 3 })
      const { w } = await renderPage()
      await flushPromises()
      await w.get('input[type=checkbox]').setValue(true)

      expect(w.get('[role=alert]').text()).toContain(PAPER_FAILED)
      expect((start(w).element as HTMLButtonElement).disabled).toBe(true)

      paperReplies({ status: 'pending', written: 1, total: 3 })
      await w.findAll('button').find((b) => b.text() === 'Try again')!.trigger('click')
      await flushPromises()
      expect(w.text()).toContain(`${PAPER_PREPARING}: 1 of 3 ready`)
      expect(asked).toEqual(['GET /api/session/s1/paper'])
      expect(vi.mocked(api).mock.calls.at(-1)).toEqual([
        '/api/session/s1/paper/retry',
        { method: 'POST' },
      ])
    })

    it('says nothing about asking again while the wait is short', async () => {
      vi.useFakeTimers({ toFake: ['setTimeout', 'clearTimeout'] })
      paperReplies({ status: 'pending', written: 1, total: 3, waited_s: 120, can_retry: false })
      const { w } = await renderPage()
      await flushPromises()

      expect(w.text()).toContain(PAPER_PREPARING)
      expect(w.text()).not.toContain(PAPER_SLOW)
      expect(w.findAll('button').some((b) => b.text() === PAPER_SLOW_RETRY)).toBe(false)
    })

    it('offers to ask again once the wait has gone on too long, and starts the wait afresh', async () => {
      vi.useFakeTimers({ toFake: ['setTimeout', 'clearTimeout'] })
      const asked = paperReplies({ status: 'pending', written: 1, total: 3, waited_s: 700, can_retry: true })
      const { w } = await renderPage()
      await flushPromises()
      await w.get('input[type=checkbox]').setValue(true)

      expect(w.text()).toContain(PAPER_SLOW)
      expect(w.text()).toContain('Your time has still not started')
      expect((start(w).element as HTMLButtonElement).disabled).toBe(true) // still not ready

      paperReplies({ status: 'pending', written: 1, total: 3, waited_s: 0, can_retry: false })
      await w.findAll('button').find((b) => b.text() === PAPER_SLOW_RETRY)!.trigger('click')
      await flushPromises()

      expect(vi.mocked(api).mock.calls.at(-1)).toEqual(['/api/session/s1/paper/retry', { method: 'POST' }])
      expect(asked).toEqual(['GET /api/session/s1/paper']) // before the tap, nothing else was asked
      expect(w.text()).not.toContain(PAPER_SLOW)
      expect(w.text()).toContain(`${PAPER_PREPARING}: 1 of 3 ready`)
    })

    it('keeps waiting, with no error shown, if the server says the questions are not ready', async () => {
      vi.useFakeTimers({ toFake: ['setTimeout', 'clearTimeout'] })
      const asked = paperReplies({ status: 'ready' })
      const { w } = await renderPage()
      await flushPromises()
      // the page thought it was ready; the server disagrees at the moment of starting
      vi.mocked(api).mockImplementation((async (path: string) => {
        if (path.endsWith('/begin')) throw new ApiError(409, 'paper_not_ready', { paper_status: 'pending' })
        return { status: 'pending', written: 2, total: 3 }
      }) as never)
      await agreeAndStart(w)
      await flushPromises()

      expect(asked.length).toBe(1)
      expect(w.text()).toContain(`${PAPER_PREPARING}: 2 of 3 ready`)
      expect(w.text()).not.toContain('Something went wrong')
      expect(w.text()).not.toContain('test page')
    })
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
