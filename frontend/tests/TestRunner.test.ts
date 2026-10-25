import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import TestRunner from '../src/candidate/TestRunner.vue'
import { CAMERA_LOST_BANNER, FLAG_NOTICE, FULLSCREEN_COVER_TITLE } from '../src/candidate/copy'
import { api, ApiError } from '../src/lib/api'
import type { QuestionResponse } from '../src/lib/api'
import { logEvent } from '../src/lib/eventLog'
import { clearNotice, noteRecorded } from '../src/lib/flagNotice'
import { startTestRuntime } from '../src/lib/runtime'
import { clearSession, saveSession } from '../src/lib/session'
import { fs, resetFullscreen, setFullscreen } from './helpers/fakeFullscreen'
import { mountPage, settle } from './helpers/render'

vi.mock('../src/lib/api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../src/lib/api')>()
  return { ...actual, api: vi.fn() }
})
vi.mock('../src/lib/fullscreen', async () => (await import('./helpers/fakeFullscreen')).fullscreenModule)
// the background work has its own tests; here only that the page starts it and what it logs
vi.mock('../src/lib/runtime', () => ({ startTestRuntime: vi.fn() }))
vi.mock('../src/lib/eventLog', () => ({ logEvent: vi.fn(() => Promise.resolve()) }))

// a recording whose state a test can change, for the camera-lost banner
const rec = vi.hoisted(() => ({ state: 'off', listeners: new Set<() => void>() }))
vi.mock('../src/lib/recording', () => ({
  recordingState: () => rec.state,
  onRecordingState: (listener: () => void) => {
    rec.listeners.add(listener)
    return () => rec.listeners.delete(listener)
  },
}))
const setRecordingState = (state: string) => {
  rec.state = state
  rec.listeners.forEach((listener) => listener())
}

const TOTAL = 3
const advance = (ms: number) => vi.advanceTimersByTimeAsync(ms)
const wait = (ms = 0) => settle(advance, ms)

let current = 1
let remaining = 600
let shown: Partial<QuestionResponse> = {}

const question = (position: number): QuestionResponse => ({
  position,
  total: TOTAL,
  section: 'numerical',
  text: `Question text ${position}`,
  options: [1, 2, 3, 4].map((n) => ({ id: position * 10 + n, text: `Option ${position}.${n}` })),
  remaining_s: remaining,
  question_remaining_s: 105,
  images: [],
  ...shown,
})

function serve() {
  vi.mocked(api).mockImplementation((async (path: string) => {
    if (path.endsWith('/question')) return question(current)
    current += 1
    return { done: current > TOTAL, remaining_s: remaining - 10 }
  }) as unknown as typeof api)
}

async function renderPage() {
  const { wrapper, router } = await mountPage('/test', {
    '/test': TestRunner,
    '/done': 'done page',
    '/candidate': 'start page',
  })
  await wait()
  return { w: wrapper, router }
}

type Page = Awaited<ReturnType<typeof renderPage>>['w']
const button = (w: Page, name: string) => w.findAll('button').find((b) => b.text().trim() === name)!
const disabled = (w: Page, name: string) => (button(w, name).element as HTMLButtonElement).disabled
const timer = (w: Page) => w.get('[role=timer]')

async function choose(w: Page, text: string) {
  const label = w.findAll('label.option').find((l) => l.text().includes(text))!
  await label.get('input').setValue(true)
}

describe('TestRunner', () => {
  beforeEach(() => {
    vi.useFakeTimers({ toFake: ['setTimeout', 'clearTimeout', 'setInterval', 'clearInterval', 'performance', 'Date'] })
    current = 1
    shown = {}
    remaining = 600
    resetFullscreen()
    setFullscreen(true) // the candidate arrives in full screen
    saveSession('s1', 'tok')
    vi.mocked(api).mockReset()
    serve()
  })

  afterEach(() => {
    document.body.innerHTML = ''
    clearSession()
    vi.useRealTimers()
    vi.unstubAllEnvs()
  })

  it('shows one question at a time, with its place and the time left', async () => {
    const { w } = await renderPage()
    expect(w.text()).toContain('Question 1 of 3')
    expect(w.text()).toContain('numerical') // capitalised by CSS
    expect(w.text()).toContain('Question text 1')
    expect(w.findAll('label.option')).toHaveLength(4)
    expect(timer(w).text()).toBe('10:00')
    expect(w.get('[role=progressbar]').attributes('aria-valuenow')).toBe('0')
  })

  describe('the notice that something was recorded', () => {
    afterEach(clearNotice)

    it('appears over the question without moving it or touching the clocks', async () => {
      const { w } = await renderPage()
      const before = [timer(w).text(), w.get('#question-text').text()]
      expect(w.text()).not.toContain(FLAG_NOTICE)

      noteRecorded(0)
      await wait()
      expect(w.get('[role=status].flag-notice').text()).toBe(FLAG_NOTICE)
      expect([timer(w).text(), w.get('#question-text').text()]).toEqual(before)
      expect(disabled(w, 'Skip')).toBe(false) // the answer buttons are still usable
      expect(vi.mocked(api)).toHaveBeenCalledTimes(1) // it asked the server nothing
    })
  })

  describe('a question that depends on a picture', () => {
    const PICTURES = ['/api/session/s1/image/7?t=aaa', '/api/session/s1/image/8?t=bbb']

    afterEach(() => {
      shown = {}
    })

    it('puts each picture where the text says, between its paragraphs', async () => {
      shown = {
        text: 'Study the chart.\n\n[[image 1]]\n\nWhich bar is tallest?\n\n[[image 2]]',
        images: PICTURES,
      }
      const { w } = await renderPage()
      const inside = w.get('#question-text')
      const kinds = inside.findAll('p, img').map((e) => e.element.tagName.toLowerCase())
      expect(kinds).toEqual(['p', 'img', 'p', 'img'])
      const pictures = inside.findAll('img')
      expect(pictures.map((i) => i.attributes('src'))).toEqual(PICTURES)
      expect(pictures[0].attributes('alt')).toBe('Picture 1 for this question')
      expect(inside.findAll('p').map((p) => p.text())).toEqual([
        'Study the chart.',
        'Which bar is tallest?',
      ])
      expect(inside.text()).not.toContain('[[image')
    })

    it('shows a question with no picture as plain text and no image element', async () => {
      const { w } = await renderPage()
      expect(w.find('#question-text img').exists()).toBe(false)
      expect(w.get('#question-text').text()).toBe('Question text 1')
    })

    it('drops a marker that has no picture behind it rather than show stray brackets', async () => {
      shown = { text: 'Look.\n\n[[image 3]]\n\nThen answer.', images: [PICTURES[0]] }
      const { w } = await renderPage()
      expect(w.find('#question-text img').exists()).toBe(false)
      expect(w.get('#question-text').text()).not.toContain('[[')
      expect(w.get('#question-text').text()).toContain('Then answer.')
    })

    it('keeps the question selectable as one block, which is what copy detection watches', async () => {
      shown = { text: 'A.\n\n[[image 1]]\n\nB.', images: [PICTURES[0]] }
      const { w } = await renderPage()
      expect(w.findAll('#question-text')).toHaveLength(1)
      expect(w.get('#question-text').classes()).toContain('question-text')
    })
  })

  it('does not offer an answer to the whole paper: only the current question is asked for', async () => {
    await renderPage()
    expect(vi.mocked(api).mock.calls.map((c) => c[0])).toEqual(['/api/session/s1/question'])
  })

  it('cannot submit before an option is chosen, then sends the position and the option', async () => {
    const { w } = await renderPage()
    expect(disabled(w, 'Submit')).toBe(true)

    await choose(w, 'Option 1.2')
    expect(disabled(w, 'Submit')).toBe(false)
    await button(w, 'Submit').trigger('click')
    await wait()

    const post = vi.mocked(api).mock.calls.find((c) => c[0].endsWith('/answer'))!
    expect(post[1]).toMatchObject({ method: 'POST', body: { position: 1, option_id: 12 } })
    expect(w.text()).toContain('Question 2 of 3')
    expect(disabled(w, 'Submit')).toBe(true) // nothing is pre-selected on the next question
  })

  it('lets the candidate skip, which sends the position only', async () => {
    const { w } = await renderPage()
    await button(w, 'Skip').trigger('click')
    await wait()
    const post = vi.mocked(api).mock.calls.find((c) => c[0].endsWith('/skip'))!
    expect(post[1]).toMatchObject({ body: { position: 1 } })
    expect(w.text()).toContain('Question 2 of 3')
  })

  it('goes to the end of the test when the last question is answered', async () => {
    current = TOTAL
    const { w } = await renderPage()
    await choose(w, 'Option 3.1')
    await button(w, 'Submit').trigger('click')
    await wait()
    expect(w.text()).toContain('done page')
  })

  it('goes to the end when the server says time is up', async () => {
    vi.mocked(api).mockRejectedValue(new ApiError(410, 'time_up', {}))
    const { w } = await renderPage()
    expect(w.text()).toContain('done page')
  })

  it('shows the question\'s own time and asks for the next question when it runs out', async () => {
    shown = { question_remaining_s: 3 }
    const { w } = await renderPage()
    expect(w.text()).toContain('This question 00:03')

    shown = {} // the next question comes with its full 1 min 45 s
    current = 2 // the server closed question 1 at 0 and moved on
    await wait(3500)
    expect(w.text()).toContain('Question 2 of 3')
    expect(w.text()).toContain('This question 01:45')
  })

  it('goes to the start page when there is no session', async () => {
    clearSession()
    const { w } = await renderPage()
    expect(w.text()).toContain('start page')
  })

  it('reloads the question when the server says it was not the current one', async () => {
    const { w } = await renderPage()
    current = 2 // another tab moved on
    vi.mocked(api).mockImplementationOnce(async () => {
      throw new ApiError(409, 'not_current', { current_position: 2 })
    })
    await choose(w, 'Option 1.1')
    await button(w, 'Submit').trigger('click')
    await wait()
    expect(w.text()).toContain('Question 2 of 3')
  })

  it('counts down from the server time, not from the device clock', async () => {
    const { w } = await renderPage()
    await wait(5000)
    expect(timer(w).text()).toBe('09:55')

    // the next response says 100 s are left: the display follows the server
    remaining = 100
    await choose(w, 'Option 1.1')
    await button(w, 'Submit').trigger('click')
    await wait()
    expect(timer(w).text()).toBe('01:40')
  })

  it('turns the timer amber below five minutes and red below one', async () => {
    remaining = 250
    shown = { question_remaining_s: 1e6 } // this test is about the whole-test timer only
    const { w } = await renderPage()
    expect(timer(w).classes()).toContain('warn')
    expect(timer(w).classes()).not.toContain('danger')

    await wait(200_000) // 50 s left
    expect(timer(w).classes()).toContain('danger')
  })

  it('asks the server again when the clock reaches zero', async () => {
    remaining = 2
    const { w } = await renderPage()
    const before = vi.mocked(api).mock.calls.length
    vi.mocked(api).mockRejectedValue(new ApiError(410, 'time_up', {}))
    await wait(2500)
    expect(vi.mocked(api).mock.calls.length).toBeGreaterThan(before)
    expect(w.text()).toContain('done page')
  })

  it('asks before the page is reloaded or closed, and keeps Back on this page', async () => {
    await renderPage()
    const unload = new Event('beforeunload', { cancelable: true })
    window.dispatchEvent(unload)
    expect(unload.defaultPrevented).toBe(true)

    const before = window.history.length
    window.dispatchEvent(new PopStateEvent('popstate'))
    expect(window.history.length).toBe(before + 1) // it pushed the page back onto the stack
  })

  describe('full screen', () => {
    it('covers the question when the candidate leaves full screen, and says the clock is running', async () => {
      const { w } = await renderPage()
      expect(w.find('[role=dialog]').exists()).toBe(false)

      setFullscreen(false)
      await wait()
      const cover = w.get('[role=dialog]')
      expect(cover.text()).toContain(FULLSCREEN_COVER_TITLE)
      expect(cover.text()).toContain('clock has not stopped')
      expect(cover.text()).toMatch(/Time left\s+\d\d:\d\d/)
    })

    it('makes the question unreachable while it is covered', async () => {
      const { w } = await renderPage()
      setFullscreen(false)
      await wait()
      expect(w.find('[inert]').exists()).toBe(true)
    })

    it('clears the cover the moment the candidate is back in full screen', async () => {
      const { w } = await renderPage()
      setFullscreen(false)
      await wait()
      expect(w.find('[role=dialog]').exists()).toBe(true)

      await button(w, 'Return to full screen').trigger('click')
      await wait(500)
      expect(fs.active).toBe(true)
      expect(w.find('[role=dialog]').exists()).toBe(false)
      expect(w.find('[inert]').exists()).toBe(false)
    })

    it('does not stop the clock while covered', async () => {
      const { w } = await renderPage()
      setFullscreen(false)
      await wait(3000)
      expect(w.get('[role=dialog]').text()).toContain('09:57')
    })

    it('shows no cover when full screen is switched off for an automated run', async () => {
      vi.stubEnv('VITE_FULLSCREEN', 'off')
      setFullscreen(false)
      const { w } = await renderPage()
      expect(w.find('[role=dialog]').exists()).toBe(false)
    })
  })
})

describe('TestRunner and the record of the test', () => {
  beforeEach(() => {
    vi.useFakeTimers({ toFake: ['setTimeout', 'clearTimeout', 'setInterval', 'clearInterval', 'performance', 'Date'] })
    current = 1
    remaining = 600
    resetFullscreen()
    setFullscreen(true)
    saveSession('s1', 'tok')
    vi.mocked(api).mockReset()
    vi.mocked(logEvent).mockClear()
    vi.mocked(startTestRuntime).mockClear()
    serve()
  })

  afterEach(() => {
    document.body.innerHTML = ''
    clearSession()
    vi.useRealTimers()
  })

  const names = () => vi.mocked(logEvent).mock.calls.map((call) => [call[0], call[1]])

  it('starts the log, the heartbeat, the watchers and the recording for this session', async () => {
    await renderPage()
    expect(startTestRuntime).toHaveBeenCalledWith('s1')
  })

  it('does not turn the camera back on for a test the server says is over', async () => {
    vi.mocked(api).mockRejectedValue(new ApiError(409, 'finished', {}))
    const { w } = await renderPage()
    expect(w.text()).toContain('done page')
    expect(startTestRuntime).not.toHaveBeenCalled()
  })

  it('starts it once, however many times the question is fetched', async () => {
    await renderPage()
    remaining = 0
    await wait(1000) // the clock at zero asks the server again
    expect(startTestRuntime).toHaveBeenCalledTimes(1)
  })

  it('does not start any of it without a session', async () => {
    clearSession()
    await renderPage()
    expect(startTestRuntime).not.toHaveBeenCalled()
  })

  it('logs each question as opened once, not again when the server only re-syncs', async () => {
    const { w } = await renderPage()
    expect(names()).toEqual([['question_opened', { position: 1 }]])

    // the clock reaching zero asks the server again; it is the same question
    remaining = 0
    await wait(1000)
    expect(names().filter((e) => e[0] === 'question_opened')).toHaveLength(1)
    expect(w.text()).toContain('Question 1 of 3')
  })

  it('logs the answer, then the next question opening', async () => {
    const { w } = await renderPage()
    await choose(w, 'Option 1.2')
    await button(w, 'Submit').trigger('click')
    await wait()

    expect(names()).toEqual([
      ['question_opened', { position: 1 }],
      ['answered', { position: 1 }],
      ['question_opened', { position: 2 }],
    ])
  })

  it('logs a skip as a skip', async () => {
    const { w } = await renderPage()
    await button(w, 'Skip').trigger('click')
    await wait()
    expect(names()).toContainEqual(['skipped', { position: 1 }])
    expect(names()).not.toContainEqual(['answered', { position: 1 }])
  })

  it('logs the last answer before it leaves for the finish page', async () => {
    current = TOTAL
    const { w, router } = await renderPage()
    await choose(w, `Option ${TOTAL}.1`)
    await button(w, 'Submit').trigger('click')
    await wait()

    expect(names()).toContainEqual(['answered', { position: TOTAL }])
    expect(router.currentRoute.value.path).toBe('/done')
  })

  it('logs nothing for an answer the server refused', async () => {
    const { w } = await renderPage()
    vi.mocked(api).mockImplementation((async (path: string) => {
      if (path.endsWith('/question')) return question(1)
      throw new ApiError(409, 'not_current', {})
    }) as unknown as typeof api)
    await choose(w, 'Option 1.1')
    await button(w, 'Submit').trigger('click')
    await wait()
    expect(names().filter((e) => e[0] === 'answered')).toEqual([])
  })

  it('warns, without stopping anything, when the camera is lost', async () => {
    const { w } = await renderPage()
    expect(w.text()).not.toContain(CAMERA_LOST_BANNER)

    setRecordingState('lost')
    await wait()

    expect(w.text()).toContain(CAMERA_LOST_BANNER)
    expect(disabled(w, 'Skip')).toBe(false) // the test carries on
    expect(timer(w).text()).not.toBe('--:--')
  })
})
