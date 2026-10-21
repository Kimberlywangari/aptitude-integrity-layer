import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { resetConnection } from '../src/lib/connection'
import {
  ageOf,
  flushEvents,
  logEvent,
  resetEventLog,
  startEventLog,
  stopEventLog,
} from '../src/lib/eventLog'
import { clearSession, saveSession } from '../src/lib/session'
import { createMemoryStore, setStore } from '../src/lib/store'
import type { DeviceStore } from '../src/lib/store'

const fetchMock = vi.fn()
const advance = (ms: number) => vi.advanceTimersByTimeAsync(ms)

function reply(status: number, body: unknown = { accepted: 1, duplicates: 0, rejected: 0 }) {
  return Promise.resolve(new Response(JSON.stringify(body), { status }))
}

type Sent = { client_seq: number; type: string; age_ms: number; payload?: Record<string, unknown> }
const sentBatches = (): Sent[][] => fetchMock.mock.calls.map((call) => JSON.parse(call[1].body).events)
const sentSeqs = () => sentBatches().flat().map((e) => e.client_seq)

describe('event log', () => {
  let store: DeviceStore

  beforeEach(() => {
    vi.useFakeTimers({
      toFake: ['setTimeout', 'clearTimeout', 'setInterval', 'clearInterval', 'performance', 'Date'],
    })
    vi.stubGlobal('fetch', fetchMock)
    fetchMock.mockReset()
    fetchMock.mockImplementation(() => reply(200))
    sessionStorage.clear()
    store = createMemoryStore()
    setStore(store)
    resetConnection()
    resetEventLog()
    saveSession('s1', 'tok')
  })

  afterEach(() => {
    stopEventLog()
    vi.useRealTimers()
    vi.unstubAllGlobals()
    clearSession()
  })

  it('writes an event to the device first, numbered from zero, and sends nothing yet', async () => {
    await logEvent('focus_lost')
    await logEvent('focus_returned')

    expect((await store.events('s1', 10)).map((e) => [e.seq, e.type])).toEqual([
      [0, 'focus_lost'],
      [1, 'focus_returned'],
    ])
    expect(fetchMock).not.toHaveBeenCalled()
  })

  it('keeps events in the order they were logged, however fast they come', async () => {
    void logEvent('a')
    void logEvent('b')
    await logEvent('c')
    expect((await store.events('s1', 10)).map((e) => e.type)).toEqual(['a', 'b', 'c'])
  })

  it('sends what is waiting within two seconds, with how long ago each thing happened', async () => {
    startEventLog('s1')
    await advance(0)
    fetchMock.mockClear()

    await logEvent('focus_lost')
    await advance(500)
    await logEvent('focus_returned', undefined)
    await advance(1_600)

    expect(fetchMock).toHaveBeenCalledTimes(1)
    const [path, init] = fetchMock.mock.calls[0]
    expect(path).toBe('/api/events')
    expect(init.method).toBe('POST')
    expect(init.headers.Authorization).toBe('Bearer tok')
    const [first, second] = sentBatches()[0]
    expect([first.client_seq, first.type, second.client_seq, second.type]).toEqual([
      0, 'focus_lost', 1, 'focus_returned',
    ])
    expect(first.age_ms - second.age_ms).toBe(500) // the older one is older by what really passed
    expect(first.age_ms).toBeGreaterThan(1_000)
  })

  it('sends a payload only when there is one', async () => {
    await logEvent('copy_attempt', { length: 240 })
    await logEvent('focus_lost')
    await flushEvents()

    const [copy, focus] = sentBatches()[0]
    expect(copy.payload).toEqual({ length: 240 })
    expect('payload' in focus).toBe(false)
  })

  it('removes events from the device only once the server has them', async () => {
    await logEvent('focus_lost')
    fetchMock.mockImplementationOnce(() => reply(200))
    await flushEvents()
    expect(await store.events('s1', 10)).toEqual([])

    await logEvent('focus_returned')
    fetchMock.mockImplementationOnce(() => Promise.reject(new TypeError('Failed to fetch')))
    expect(await flushEvents()).toBe(false)
    expect(await store.events('s1', 10)).toHaveLength(1) // still there to send again
  })

  it('counts a repeat the server already had as delivered', async () => {
    await logEvent('focus_lost')
    fetchMock.mockImplementationOnce(() => reply(200, { accepted: 0, duplicates: 1, rejected: 0 }))
    await flushEvents()
    expect(await store.events('s1', 10)).toEqual([])
  })

  it('sends at once, without waiting for the timer, when twenty are waiting', async () => {
    startEventLog('s1')
    await advance(0)
    fetchMock.mockClear()

    for (let i = 0; i < 20; i++) void logEvent('focus_lost')
    await logEvent('focus_returned')
    await advance(0)

    expect(fetchMock).toHaveBeenCalled()
    expect(sentSeqs().slice(0, 20)).toEqual([...Array(20).keys()])
  })

  it('sends in batches of at most 100, in order', async () => {
    for (let i = 0; i < 230; i++) await logEvent('focus_lost')
    await flushEvents()

    expect(sentBatches().map((batch) => batch.length)).toEqual([100, 100, 30])
    expect(sentSeqs()).toEqual([...Array(230).keys()])
  })

  describe('when the connection fails', () => {
    it('waits 1 s, then 2 s, then delivers everything once and in order', async () => {
      startEventLog('s1')
      await advance(0)
      fetchMock.mockClear()
      fetchMock.mockImplementationOnce(() => Promise.reject(new TypeError('Failed to fetch')))
      fetchMock.mockImplementationOnce(() => Promise.reject(new TypeError('Failed to fetch')))

      await logEvent('focus_lost')
      await logEvent('focus_returned')
      await advance(2_100) // the timer fires; the first attempt fails
      expect(fetchMock).toHaveBeenCalledTimes(1)

      await advance(1_300) // after about 1 s: the second attempt fails
      expect(fetchMock).toHaveBeenCalledTimes(2)

      await advance(2_600) // after about 2 s: the third gets through
      expect(fetchMock).toHaveBeenCalledTimes(3)
      expect(sentBatches()[2].map((e) => e.client_seq)).toEqual([0, 1])
      expect(await store.events('s1', 10)).toEqual([])

      await advance(10_000) // and nothing is sent again
      expect(fetchMock).toHaveBeenCalledTimes(3)
    })

    it('gives a late event its true age, not the moment it finally got through', async () => {
      await logEvent('focus_lost')
      fetchMock.mockImplementationOnce(() => Promise.reject(new TypeError('offline')))
      await flushEvents()
      await advance(90_000) // offline for a minute and a half

      await flushEvents()
      expect(sentBatches()[1][0].age_ms).toBeGreaterThanOrEqual(90_000)
    })

    it('treats a refusal that will never change (a 4xx) as done, so it cannot block the rest', async () => {
      await logEvent('bad')
      fetchMock.mockImplementationOnce(() => reply(422, { code: 'validation' }))
      await flushEvents()

      expect(await store.events('s1', 10)).toEqual([])
      await logEvent('focus_lost')
      await flushEvents()
      expect(sentBatches().at(-1)?.[0].type).toBe('focus_lost')
    })

    it('tries again after a server error', async () => {
      await logEvent('focus_lost')
      fetchMock.mockImplementationOnce(() => reply(503, { code: 'unavailable' }))
      expect(await flushEvents()).toBe(false)
      expect(await flushEvents()).toBe(true)
      expect(fetchMock).toHaveBeenCalledTimes(2)
    })

    it('stops sending for good when the server will not accept the token', async () => {
      await logEvent('focus_lost')
      fetchMock.mockImplementationOnce(() => reply(401, { code: 'unauthorized' }))
      await flushEvents()
      fetchMock.mockClear()

      await logEvent('focus_returned')
      await flushEvents()
      expect(fetchMock).not.toHaveBeenCalled()
      expect(await store.events('s1', 10)).toHaveLength(2) // kept, in case a new session starts
    })
  })

  describe('when the page goes away', () => {
    const hide = () => {
      Object.defineProperty(document, 'visibilityState', { value: 'hidden', configurable: true })
      document.dispatchEvent(new Event('visibilitychange'))
    }

    afterEach(() => {
      Object.defineProperty(document, 'visibilityState', { value: 'visible', configurable: true })
    })

    it('sends what it has at once, in a request that outlives the page, with the last event in it', async () => {
      startEventLog('s1')
      await advance(0)
      fetchMock.mockClear()

      void logEvent('visibility_hidden') // logged an instant before the page hid
      hide()
      await advance(0)

      expect(fetchMock).toHaveBeenCalledTimes(1)
      expect(fetchMock.mock.calls[0][1].keepalive).toBe(true)
      expect(sentBatches()[0].map((e) => e.type)).toEqual(['visibility_hidden'])
    })

    it('does nothing when the page comes back', async () => {
      startEventLog('s1')
      await advance(0)
      fetchMock.mockClear()
      document.dispatchEvent(new Event('visibilitychange'))
      await advance(0)
      expect(fetchMock).not.toHaveBeenCalled()
    })
  })

  it('sends what an earlier page life left behind as soon as it starts', async () => {
    await logEvent('focus_lost') // "before the reload"
    resetEventLog()
    fetchMock.mockClear()

    startEventLog('s1')
    await advance(0)

    expect(sentBatches()[0].map((e) => e.type)).toEqual(['focus_lost'])
  })

  it('never throws, whatever goes wrong underneath', async () => {
    setStore({
      ...store,
      nextCounter: () => Promise.reject(new Error('disk full')),
    })
    await expect(logEvent('focus_lost')).resolves.toBeUndefined()
  })

  it('logs nothing when there is no session', async () => {
    clearSession()
    resetEventLog()
    await logEvent('focus_lost')
    expect(await store.events('s1', 10)).toEqual([])
  })
})

describe('ageOf()', () => {
  beforeEach(() => {
    vi.useFakeTimers({ toFake: ['performance', 'Date'] })
  })
  afterEach(() => vi.useRealTimers())

  // read while the fake clock is in place: it is the one the code under test reads too
  const origin = () => performance.timeOrigin ?? 0

  it('uses the monotonic clock within one page life', () => {
    vi.advanceTimersByTime(3_000)
    const now = performance.now()
    expect(ageOf({ mono: now - 1_250, origin: origin(), epoch: 0 })).toBe(1_250)
  })

  it('uses the wall clock once the page has been reloaded', () => {
    const epoch = Date.now() - 40_000
    expect(ageOf({ mono: 5, origin: origin() + 1, epoch })).toBe(40_000)
  })

  it('is never negative and never older than the server accepts', () => {
    expect(ageOf({ mono: performance.now() + 500, origin: origin(), epoch: 0 })).toBe(0)
    expect(ageOf({ mono: 0, origin: origin() + 1, epoch: Date.now() - 10 * 24 * 3_600_000 })).toBe(
      48 * 3_600_000 - 1,
    )
  })
})
