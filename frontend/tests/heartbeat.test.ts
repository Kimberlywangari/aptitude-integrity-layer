import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { resetConnection } from '../src/lib/connection'
import { HEARTBEAT_MS, startHeartbeat } from '../src/lib/heartbeat'
import { clearSession, saveSession } from '../src/lib/session'

const fetchMock = vi.fn()
const advance = (ms: number) => vi.advanceTimersByTimeAsync(ms)

const beat = { server_time: '2026-10-19T09:00:00Z', remaining_s: 1500, status: 'in_progress' }
const ok = () => Promise.resolve(new Response(JSON.stringify(beat), { status: 200 }))

class FakeWorker {
  static all: FakeWorker[] = []
  onmessage: (() => void) | null = null
  onerror: (() => void) | null = null
  posted: unknown[] = []
  terminated = false
  constructor(public url: string) {
    FakeWorker.all.push(this)
  }
  postMessage(message: unknown) {
    this.posted.push(message)
  }
  terminate() {
    this.terminated = true
  }
}

describe('heartbeat', () => {
  let stop: () => void

  beforeEach(() => {
    vi.useFakeTimers({ toFake: ['setTimeout', 'clearTimeout', 'setInterval', 'clearInterval', 'performance'] })
    vi.stubGlobal('fetch', fetchMock)
    fetchMock.mockReset()
    fetchMock.mockImplementation(ok)
    resetConnection()
    saveSession('s1', 'tok')
  })

  afterEach(() => {
    stop?.()
    vi.useRealTimers()
    vi.unstubAllGlobals()
    clearSession()
  })

  describe('with a plain timer (no worker in this browser)', () => {
    it('beats at once, then every 10 seconds', async () => {
      stop = startHeartbeat()
      await advance(0)
      expect(fetchMock).toHaveBeenCalledTimes(1)

      await advance(HEARTBEAT_MS)
      expect(fetchMock).toHaveBeenCalledTimes(2)
      await advance(HEARTBEAT_MS * 2)
      expect(fetchMock).toHaveBeenCalledTimes(4)

      const [path, init] = fetchMock.mock.calls[0]
      expect(path).toBe('/api/heartbeat')
      expect(init.method).toBe('POST')
      expect(init.headers.Authorization).toBe('Bearer tok')
    })

    it('hands each answer to whoever wants the server’s time left', async () => {
      const seen = vi.fn()
      stop = startHeartbeat(seen)
      await advance(0)
      expect(seen).toHaveBeenCalledWith(beat)
    })

    it('does not pile requests up behind a slow one', async () => {
      fetchMock.mockImplementation(() => new Promise(() => undefined)) // never answers
      stop = startHeartbeat()
      await advance(HEARTBEAT_MS * 5)
      expect(fetchMock).toHaveBeenCalledTimes(1)
    })

    it('keeps beating after a missed one: the gap is for the server to see', async () => {
      fetchMock.mockImplementationOnce(() => Promise.reject(new TypeError('Failed to fetch')))
      stop = startHeartbeat()
      await advance(0)
      await advance(HEARTBEAT_MS)
      expect(fetchMock).toHaveBeenCalledTimes(2)
    })

    it('stops for good when the server will not accept the token', async () => {
      fetchMock.mockImplementation(() => Promise.resolve(new Response('{"code":"unauthorized"}', { status: 401 })))
      stop = startHeartbeat()
      await advance(0)
      await advance(HEARTBEAT_MS * 3)
      expect(fetchMock).toHaveBeenCalledTimes(1)
    })

    it('can be stopped, and started again afterwards', async () => {
      stop = startHeartbeat()
      await advance(0)
      stop()
      stop() // twice is fine
      await advance(HEARTBEAT_MS * 3)
      expect(fetchMock).toHaveBeenCalledTimes(1)

      stop = startHeartbeat()
      await advance(0)
      expect(fetchMock).toHaveBeenCalledTimes(2)
    })

    it('starting twice is the same heartbeat, not two', async () => {
      stop = startHeartbeat()
      expect(startHeartbeat()).toBe(stop)
      await advance(HEARTBEAT_MS)
      expect(fetchMock).toHaveBeenCalledTimes(2) // the first one, and one tick
    })
  })

  describe('with a worker providing the tick', () => {
    beforeEach(() => {
      FakeWorker.all = []
      vi.stubGlobal('Worker', FakeWorker)
      URL.createObjectURL = vi.fn(() => 'blob:heartbeat')
      URL.revokeObjectURL = vi.fn()
    })

    it('asks the worker for a tick every 10 s and beats on each', async () => {
      stop = startHeartbeat()
      await advance(0)
      const [worker] = FakeWorker.all
      expect(worker.posted).toEqual([{ every: HEARTBEAT_MS }])

      worker.onmessage?.()
      await advance(0)
      expect(fetchMock).toHaveBeenCalledTimes(2)

      await advance(HEARTBEAT_MS * 3) // the page’s own timer is not what beats now
      expect(fetchMock).toHaveBeenCalledTimes(2)
    })

    it('falls back to a plain timer if the worker fails', async () => {
      stop = startHeartbeat()
      await advance(0)
      FakeWorker.all[0].onerror?.()

      expect(FakeWorker.all[0].terminated).toBe(true)
      await advance(HEARTBEAT_MS)
      expect(fetchMock).toHaveBeenCalledTimes(2)
    })

    it('lets the worker go when stopped', async () => {
      stop = startHeartbeat()
      stop()
      expect(FakeWorker.all[0].terminated).toBe(true)
      expect(URL.revokeObjectURL).toHaveBeenCalledWith('blob:heartbeat')
    })
  })
})
