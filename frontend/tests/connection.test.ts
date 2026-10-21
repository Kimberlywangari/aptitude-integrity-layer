import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { ApiError } from '../src/lib/api'
import {
  isConnectionLost,
  onConnectionChange,
  reportBrowserOffline,
  reportBrowserOnline,
  reportNoReply,
  reportReply,
  resetConnection,
  tracked,
} from '../src/lib/connection'
import type { ConnectionChange } from '../src/lib/connection'

describe('connection tracker', () => {
  const changes: ConnectionChange[] = []

  beforeEach(() => {
    vi.useFakeTimers({ toFake: ['performance'] })
    resetConnection()
    changes.length = 0
    onConnectionChange((change) => changes.push(change))
  })

  afterEach(() => vi.useRealTimers())

  it('does not call one failed request a lost connection', () => {
    reportNoReply()
    expect(isConnectionLost()).toBe(false)
    expect(changes).toEqual([])
  })

  it('calls two failures in a row lost, dated to the first of them', () => {
    reportNoReply()
    vi.advanceTimersByTime(4_000)
    reportNoReply()

    expect(isConnectionLost()).toBe(true)
    expect(changes).toHaveLength(1)
    expect(changes[0].lost).toBe(true)
    expect(performance.now() - changes[0].since).toBeCloseTo(4_000, -2)
  })

  it('says so once, however long the failures go on', () => {
    for (let i = 0; i < 6; i++) reportNoReply()
    expect(changes).toHaveLength(1)
  })

  it('is restored by the next reply of any kind', () => {
    reportNoReply()
    reportNoReply()
    reportReply()

    expect(isConnectionLost()).toBe(false)
    expect(changes.map((c) => c.lost)).toEqual([true, false])
  })

  it('a reply in between means the failures were not in a row', () => {
    reportNoReply()
    reportReply()
    reportNoReply()
    expect(isConnectionLost()).toBe(false)
  })

  it('follows the browser’s own offline and online signals', () => {
    reportBrowserOffline()
    expect(isConnectionLost()).toBe(true)
    reportBrowserOnline()
    expect(isConnectionLost()).toBe(false)
    expect(changes.map((c) => c.lost)).toEqual([true, false])
  })

  describe('tracked()', () => {
    it('counts a refusal from the server as the server answering', async () => {
      reportNoReply()
      await tracked(() => Promise.reject(new ApiError(503, 'chunk_unavailable', {}))).catch(() => undefined)
      await tracked(() => Promise.reject(new ApiError(409, 'not_current', {}))).catch(() => undefined)
      expect(isConnectionLost()).toBe(false)
    })

    it('counts a request that never got an answer as a failure', async () => {
      const failing = () => Promise.reject(new TypeError('Failed to fetch'))
      await tracked(failing).catch(() => undefined)
      await tracked(failing).catch(() => undefined)
      expect(isConnectionLost()).toBe(true)
    })

    it('passes the result and the error through untouched', async () => {
      await expect(tracked(() => Promise.resolve(7))).resolves.toBe(7)
      const error = new TypeError('Failed to fetch')
      await expect(tracked(() => Promise.reject(error))).rejects.toBe(error)
    })
  })
})
