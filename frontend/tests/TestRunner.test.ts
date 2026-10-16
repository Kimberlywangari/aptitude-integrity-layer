import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import TestRunner from '../src/candidate/TestRunner.vue'
import { FULLSCREEN_COVER_TITLE } from '../src/candidate/copy'
import { api, ApiError } from '../src/lib/api'
import type { QuestionResponse } from '../src/lib/api'
import { clearSession, saveSession } from '../src/lib/session'
import { fs, resetFullscreen, setFullscreen } from './helpers/fakeFullscreen'
import { mountPage, settle } from './helpers/render'

vi.mock('../src/lib/api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../src/lib/api')>()
  return { ...actual, api: vi.fn() }
})
vi.mock('../src/lib/fullscreen', async () => (await import('./helpers/fakeFullscreen')).fullscreenModule)

const TOTAL = 3
const advance = (ms: number) => vi.advanceTimersByTimeAsync(ms)
const wait = (ms = 0) => settle(advance, ms)

let current = 1
let remaining = 600

const question = (position: number): QuestionResponse => ({
  position,
  total: TOTAL,
  section: 'numerical',
  text: `Question text ${position}`,
  options: [1, 2, 3, 4].map((n) => ({ id: position * 10 + n, text: `Option ${position}.${n}` })),
  remaining_s: remaining,
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
