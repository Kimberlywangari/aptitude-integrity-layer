import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { IDLE_AFTER_MS, startActionLogger } from '../src/lib/actionLogger'
import { resetConnection } from '../src/lib/connection'
import { logEvent } from '../src/lib/eventLog'
import { resetFullscreen, setFullscreen } from './helpers/fakeFullscreen'

vi.mock('../src/lib/eventLog', () => ({ logEvent: vi.fn(() => Promise.resolve()) }))
vi.mock('../src/lib/fullscreen', async () => (await import('./helpers/fakeFullscreen')).fullscreenModule)

const logged = () => vi.mocked(logEvent).mock.calls.map((call) => call[0])
const lastCall = () => vi.mocked(logEvent).mock.calls.at(-1)!

function selecting(text: string) {
  vi.spyOn(window, 'getSelection').mockReturnValue({ toString: () => text } as unknown as Selection)
}

function setVisibility(state: 'hidden' | 'visible') {
  Object.defineProperty(document, 'visibilityState', { value: state, configurable: true })
  document.dispatchEvent(new Event('visibilitychange'))
}

describe('action logger', () => {
  let stop: () => void

  beforeEach(() => {
    vi.useFakeTimers({ toFake: ['setInterval', 'clearInterval', 'setTimeout', 'clearTimeout', 'performance'] })
    vi.mocked(logEvent).mockClear()
    sessionStorage.clear()
    resetConnection()
    resetFullscreen()
    stop = startActionLogger()
  })

  afterEach(() => {
    stop()
    vi.restoreAllMocks()
    vi.useRealTimers()
    setVisibility('visible')
  })

  describe('page life', () => {
    it('starts with a page_load', () => {
      expect(logged()).toEqual(['page_load'])
    })

    it('says reload only when the page was reloaded while the test was already running', () => {
      stop()
      const reloaded = () =>
        vi.spyOn(performance, 'getEntriesByType').mockReturnValue([{ type: 'reload' }] as never)

      // first time in: a reload of the pre-check pages earlier is not a reload of the test
      reloaded()
      sessionStorage.clear() // beforeEach had already started it once
      vi.mocked(logEvent).mockClear()
      stop = startActionLogger()
      expect(logged()).toEqual(['page_load'])

      // the test was running (the flag is set) and the page was reloaded
      stop()
      vi.mocked(logEvent).mockClear()
      stop = startActionLogger()
      expect(logged()).toEqual(['reload'])
    })

    it('starting twice neither listens twice nor logs a second page_load', () => {
      expect(startActionLogger()).toBe(stop)
      window.dispatchEvent(new Event('blur'))
      expect(logged()).toEqual(['page_load', 'focus_lost'])
    })
  })

  describe('focus and visibility', () => {
    it('logs the window losing and getting back focus', () => {
      window.dispatchEvent(new Event('blur'))
      window.dispatchEvent(new Event('focus'))
      expect(logged().slice(1)).toEqual(['focus_lost', 'focus_returned'])
    })

    it('logs the tab being hidden and shown', () => {
      setVisibility('hidden')
      setVisibility('visible')
      expect(logged().slice(1)).toEqual(['visibility_hidden', 'visibility_visible'])
    })
  })

  describe('copy, cut, paste and right-click', () => {
    it('records how much was copied and nothing of what it said', () => {
      selecting('the secret question text')
      document.dispatchEvent(new Event('copy'))

      expect(lastCall()).toEqual(['copy_attempt', { length: 'the secret question text'.length }])
      expect(JSON.stringify(vi.mocked(logEvent).mock.calls)).not.toContain('secret')
    })

    it('does the same for cut', () => {
      selecting('abcd')
      document.dispatchEvent(new Event('cut'))
      expect(lastCall()).toEqual(['cut_attempt', { length: 4 }])
    })

    it('records an attempt to copy with nothing selected as length 0', () => {
      selecting('')
      document.dispatchEvent(new Event('copy'))
      expect(lastCall()).toEqual(['copy_attempt', { length: 0 }])
    })

    it('records paste and right-click with no detail', () => {
      document.dispatchEvent(new Event('paste'))
      document.dispatchEvent(new Event('contextmenu'))
      expect(vi.mocked(logEvent).mock.calls.slice(1)).toEqual([['paste_attempt'], ['contextmenu_attempt']])
    })

    it('blocks none of them: the proposal says a person decides what they mean', () => {
      for (const type of ['copy', 'cut', 'paste', 'contextmenu']) {
        const event = new Event(type, { cancelable: true })
        document.dispatchEvent(event)
        expect(event.defaultPrevented).toBe(false)
      }
    })
  })

  describe('full screen', () => {
    it('logs leaving and returning, as context and not as a flag', () => {
      setFullscreen(true)
      setFullscreen(false)
      expect(logged().slice(1)).toEqual(['fullscreen_entered', 'fullscreen_exited'])
    })
  })

  describe('the connection', () => {
    it('logs the browser going offline and coming back', () => {
      window.dispatchEvent(new Event('offline'))
      window.dispatchEvent(new Event('online'))
      expect(logged().slice(1)).toEqual(['connection_lost', 'connection_restored'])
    })
  })

  describe('idle', () => {
    it('logs 30 s of nothing as idle, dated to when the quiet began', () => {
      const began = performance.now()
      vi.advanceTimersByTime(IDLE_AFTER_MS + 1_000)

      const [type, payload, options] = lastCall()
      expect(type).toBe('idle_start')
      expect(payload).toBeUndefined()
      expect(options?.at).toBeCloseTo(began + IDLE_AFTER_MS, -2) // not 31 s: the quiet began at 0
    })

    it('says how long it lasted when the candidate comes back', () => {
      vi.advanceTimersByTime(IDLE_AFTER_MS + 1_000)
      vi.advanceTimersByTime(60_000)
      window.dispatchEvent(new Event('mousemove'))

      const [type, payload] = lastCall()
      expect(type).toBe('idle_end')
      expect((payload as { duration_s: number }).duration_s).toBeCloseTo(61, 0)
    })

    it('is not triggered by someone who keeps touching the page', () => {
      for (let i = 0; i < 10; i++) {
        vi.advanceTimersByTime(20_000)
        window.dispatchEvent(new Event('keydown'))
      }
      expect(logged()).not.toContain('idle_start')
    })

    it.each(['mousemove', 'mousedown', 'keydown', 'wheel', 'touchstart', 'pointerdown'])(
      'counts %s as being there',
      (type) => {
        vi.advanceTimersByTime(25_000)
        window.dispatchEvent(new Event(type))
        vi.advanceTimersByTime(25_000)
        expect(logged()).not.toContain('idle_start')
      },
    )
  })

  it('stops completely when asked: no listener, no timer', () => {
    stop()
    vi.mocked(logEvent).mockClear()

    window.dispatchEvent(new Event('blur'))
    document.dispatchEvent(new Event('copy'))
    setFullscreen(true)
    vi.advanceTimersByTime(120_000)

    expect(logEvent).not.toHaveBeenCalled()
    stop = startActionLogger() // and can be started again
    expect(logged()).toEqual(['page_load'])
  })
})
