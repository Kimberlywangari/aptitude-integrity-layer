import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { addChunk, sha256Hex } from '../src/lib/chunkQueue'
import { resetConnection } from '../src/lib/connection'
import { clearSession, saveSession } from '../src/lib/session'
import { createMemoryStore, setStore } from '../src/lib/store'
import type { DeviceStore } from '../src/lib/store'
import {
  onUploadStatus,
  resetUploader,
  startUploader,
  uploadStatus,
  waitForUploads,
  wakeUploader,
} from '../src/lib/uploader'

const fetchMock = vi.fn()
const advance = (ms: number) => vi.advanceTimersByTimeAsync(ms)
// the uploader chains many small promises (the store, the hash, the request); let them all settle
async function flush(ms = 0) {
  await advance(ms)
  for (let i = 0; i < 6; i++) await advance(0)
}

const stored = () => Promise.resolve(new Response('{"status":"stored"}', { status: 200 }))
const failWith = (status: number, code: string) =>
  Promise.resolve(new Response(JSON.stringify({ code }), { status }))
const noConnection = () => Promise.reject(new TypeError('Failed to fetch'))

const urls = () => fetchMock.mock.calls.map((call) => call[0] as string)
const seqsSent = () => urls().map((url) => Number(url.split('/').at(-1)))

describe('uploader', () => {
  let store: DeviceStore

  beforeEach(() => {
    vi.useFakeTimers({ toFake: ['setTimeout', 'clearTimeout', 'setInterval', 'clearInterval', 'performance'] })
    vi.spyOn(Math, 'random').mockReturnValue(0) // no jitter, so the waits are exact
    vi.stubGlobal('fetch', fetchMock)
    fetchMock.mockReset()
    fetchMock.mockImplementation(stored)
    sessionStorage.clear()
    store = createMemoryStore()
    setStore(store)
    resetConnection()
    resetUploader()
    saveSession('s1', 'tok')
  })

  afterEach(() => {
    resetUploader()
    vi.restoreAllMocks()
    vi.useRealTimers()
    vi.unstubAllGlobals()
    clearSession()
  })

  const make = (count: number, segment = 0) =>
    Promise.all(Array.from({ length: count }, (_, i) => addChunk('s1', segment, new Blob([`chunk-${i}`]))))

  it('sends the chunks one at a time, lowest number first, with their checksum and segment', async () => {
    const [first] = await make(3)
    startUploader('s1')
    await flush()

    expect(seqsSent()).toEqual([0, 1, 2])
    const [path, init] = fetchMock.mock.calls[0]
    expect(path).toBe('/api/chunks/s1/0')
    expect(init.method).toBe('PUT')
    expect(init.headers['X-Chunk-SHA256']).toBe(first.sha256)
    expect(init.headers['X-Chunk-SHA256']).toBe(await sha256Hex(new Blob(['chunk-0'])))
    expect(init.headers['X-Chunk-Segment']).toBe('0')
    expect(init.headers.Authorization).toBe('Bearer tok')
    expect(init.headers['Content-Type']).toBe('application/octet-stream')
    expect(init.body).toBeInstanceOf(Blob)
  })

  it('tells the server which recorder run a chunk came from', async () => {
    await make(1, 0)
    await make(1, 2)
    startUploader('s1')
    await flush()
    expect(fetchMock.mock.calls.map((call) => call[1].headers['X-Chunk-Segment'])).toEqual(['0', '2'])
  })

  it('lets go of a chunk’s bytes once the server has it, and counts it done', async () => {
    await make(2)
    startUploader('s1')
    await flush()

    expect((await store.chunks('s1')).map((c) => [c.status, c.blob])).toEqual([
      ['done', null],
      ['done', null],
    ])
    expect(uploadStatus()).toMatchObject({ total: 2, done: 2, pending: 0, failed: 0, retrying: false })
  })

  it('counts a chunk the server already held as done, the same as a new one', async () => {
    await make(1)
    fetchMock.mockImplementation(() => Promise.resolve(new Response('{"status":"duplicate"}')))
    startUploader('s1')
    await flush()
    expect(uploadStatus().done).toBe(1)
  })

  it('picks up chunks that arrive after it has gone quiet', async () => {
    startUploader('s1')
    await flush()
    expect(fetchMock).not.toHaveBeenCalled()

    await make(1)
    wakeUploader()
    await flush()
    expect(seqsSent()).toEqual([0])
  })

  describe('when the connection or the server has a bad moment', () => {
    it('waits 1 s, then 2 s, and sends the same chunk again each time, before going on', async () => {
      await make(2)
      fetchMock.mockImplementationOnce(noConnection)
      fetchMock.mockImplementationOnce(noConnection)
      startUploader('s1')

      await flush()
      expect(seqsSent()).toEqual([0]) // failed
      expect(uploadStatus().retrying).toBe(true)

      await flush(900)
      expect(seqsSent()).toEqual([0]) // still waiting
      await flush(100) // 1 s in
      expect(seqsSent()).toEqual([0, 0]) // the same chunk again, failed again

      await flush(1_900)
      expect(seqsSent()).toEqual([0, 0]) // 2 s wait, not over
      await flush(100) // 3 s in
      expect(seqsSent()).toEqual([0, 0, 0, 1]) // got through, and on to the next
      expect(uploadStatus()).toMatchObject({ done: 2, retrying: false })
    })

    it('waits longer each time, up to a minute', async () => {
      await make(1)
      fetchMock.mockImplementation(noConnection)
      startUploader('s1')
      await flush()
      for (const wait of [1, 2, 4, 8, 16, 32, 60, 60]) {
        const before = fetchMock.mock.calls.length
        await flush(wait * 1000 - 100)
        expect(fetchMock.mock.calls.length).toBe(before) // not yet
        await flush(100) // exactly the wait: the next try is made
        expect(fetchMock.mock.calls.length).toBe(before + 1)
      }
    })

    it('tries again after a refusal that is only a bad moment (503, 500, 429)', async () => {
      await make(1)
      fetchMock.mockImplementationOnce(() => failWith(503, 'chunk_unavailable'))
      fetchMock.mockImplementationOnce(() => failWith(500, 'unknown'))
      fetchMock.mockImplementationOnce(() => failWith(429, 'slow_down'))
      startUploader('s1')
      await flush(10_000)
      expect(seqsSent()).toEqual([0, 0, 0, 0])
      expect(uploadStatus().done).toBe(1)
    })

    it('goes at once when the browser says it is back online, instead of finishing its wait', async () => {
      await make(1)
      fetchMock.mockImplementationOnce(noConnection)
      startUploader('s1')
      await flush()
      expect(seqsSent()).toEqual([0])

      window.dispatchEvent(new Event('online'))
      await flush()
      expect(seqsSent()).toEqual([0, 0])
    })

    it('sends a checksum mismatch again a few times, then gives that chunk up', async () => {
      await make(2)
      fetchMock.mockImplementation((url: string) =>
        url.endsWith('/0') ? failWith(422, 'checksum_mismatch') : stored(),
      )
      startUploader('s1')
      await flush(60_000)

      expect(seqsSent().filter((seq) => seq === 0)).toHaveLength(5)
      expect(seqsSent().at(-1)).toBe(1) // and the line moves on
      expect(uploadStatus()).toMatchObject({ failed: 1, done: 1 })
    })
  })

  describe('answers that will never change', () => {
    it.each([
      [413, 'chunk_too_large'],
      [409, 'chunk_conflict'],
    ])('gives up on that chunk only, for a %s, and sends the next', async (status, code) => {
      await make(3)
      fetchMock.mockImplementation((url: string) => (url.endsWith('/1') ? failWith(status, code) : stored()))
      startUploader('s1')
      await flush()

      expect(seqsSent()).toEqual([0, 1, 2]) // 1 is tried once, not again and again
      expect((await store.chunks('s1')).map((c) => c.status)).toEqual(['done', 'failed', 'done'])
      expect(uploadStatus()).toMatchObject({ done: 2, failed: 1, halted: null })
    })

    it('stops for good, for a 401: a token the server will not accept never starts to work', async () => {
      await make(3)
      fetchMock.mockImplementationOnce(stored)
      fetchMock.mockImplementationOnce(() => failWith(401, 'unauthorized'))
      startUploader('s1')
      await flush(120_000)

      expect(seqsSent()).toEqual([0, 1])
      expect(uploadStatus()).toMatchObject({ halted: 'unauthorized', done: 1, pending: 2 })
    })

    it('stops for good when the upload window has closed (410)', async () => {
      await make(2)
      fetchMock.mockImplementation(() => failWith(410, 'upload_window_closed'))
      startUploader('s1')
      await flush(120_000)

      expect(seqsSent()).toEqual([0])
      expect(uploadStatus().halted).toBe('closed')
    })

    it('can be started again after it has stopped, for instance with a new token', async () => {
      await make(1)
      fetchMock.mockImplementationOnce(() => failWith(401, 'unauthorized'))
      startUploader('s1')
      await flush()
      expect(uploadStatus().halted).toBe('unauthorized')

      saveSession('s1', 'upload-token')
      startUploader('s1')
      await flush()
      expect(uploadStatus()).toMatchObject({ halted: null, done: 1 })
      expect(fetchMock.mock.calls.at(-1)?.[1].headers.Authorization).toBe('Bearer upload-token')
    })

    it('does not hold the line for a chunk whose bytes are gone', async () => {
      const [first] = await make(2)
      await store.putChunk({ ...first, blob: null }) // pending, but nothing to send
      startUploader('s1')
      await flush()
      expect(seqsSent()).toEqual([1])
      expect(uploadStatus()).toMatchObject({ failed: 1, done: 1 })
    })
  })

  it('starting it twice for the same session is one uploader, not two', async () => {
    await make(2)
    startUploader('s1')
    startUploader('s1')
    await flush()
    expect(seqsSent()).toEqual([0, 1])
  })

  it('tells anyone listening each time the counts change, and then stops when they do', async () => {
    const seen = vi.fn()
    const stop = onUploadStatus(seen)
    await make(2)
    startUploader('s1')
    await flush()
    expect(seen).toHaveBeenCalled()
    expect(seen.mock.calls.at(-1)?.[0].done).toBe(2)

    stop()
    seen.mockClear()
    await make(1)
    wakeUploader()
    await flush()
    expect(seen).not.toHaveBeenCalled()
  })

  describe('waitForUploads()', () => {
    it('is true as soon as that many chunks are safely with the server', async () => {
      await make(1)
      const waiting = waitForUploads(1, 30_000)
      startUploader('s1')
      await flush()
      await expect(waiting).resolves.toBe(true)
    })

    it('is true at once if they already are', async () => {
      await make(1)
      startUploader('s1')
      await flush()
      await expect(waitForUploads(1, 30_000)).resolves.toBe(true)
    })

    it('is false when the time runs out first', async () => {
      await make(1)
      fetchMock.mockImplementation(noConnection)
      startUploader('s1')
      const waiting = waitForUploads(1, 30_000)
      await flush(31_000)
      await expect(waiting).resolves.toBe(false)
    })

    it('is false at once if the uploader has been stopped by a refusal', async () => {
      await make(1)
      fetchMock.mockImplementation(() => failWith(401, 'unauthorized'))
      const waiting = waitForUploads(1, 30_000)
      startUploader('s1')
      await flush()
      await expect(waiting).resolves.toBe(false)
    })
  })
})
