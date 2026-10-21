import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import {
  AUDIO_BITS_PER_SECOND,
  CHUNK_EVERY_MS,
  FIRST_CHUNK_AFTER_MS,
  RECORDER_MIME,
  RecorderUnsupportedError,
  VIDEO_BITS_PER_SECOND,
  recorderSupported,
  startRecorder,
} from '../src/lib/recorder'
import { FakeMediaRecorder } from './helpers/fakeMedia'

const stream = {} as MediaStream
const advance = (ms: number) => vi.advanceTimersByTimeAsync(ms)

function callbacks() {
  return { onStart: vi.fn(), onChunk: vi.fn(), onError: vi.fn(), onStop: vi.fn() }
}

describe('recorder', () => {
  beforeEach(() => {
    vi.useFakeTimers({ toFake: ['setTimeout', 'clearTimeout'] })
    FakeMediaRecorder.reset()
    vi.stubGlobal('MediaRecorder', FakeMediaRecorder)
  })

  afterEach(() => {
    vi.useRealTimers()
    vi.unstubAllGlobals()
  })

  it('records video and audio at the rates the upload budget was worked out for', () => {
    startRecorder(stream, callbacks())
    const [recorder] = FakeMediaRecorder.instances
    expect(recorder.options).toEqual({
      mimeType: RECORDER_MIME,
      videoBitsPerSecond: VIDEO_BITS_PER_SECOND,
      audioBitsPerSecond: AUDIO_BITS_PER_SECOND,
    })
    expect(RECORDER_MIME).toBe('video/webm;codecs=vp8,opus')
    expect(VIDEO_BITS_PER_SECOND + AUDIO_BITS_PER_SECOND).toBe(174_000) // about 80 MB an hour
  })

  it('falls back to plain WebM when the browser will not name the codecs', () => {
    FakeMediaRecorder.supported = false
    startRecorder(stream, callbacks())
    expect(FakeMediaRecorder.instances[0].options.mimeType).toBe('video/webm')
  })

  it('hands over a piece every 10 seconds, and tells when recording has really begun', async () => {
    const cb = callbacks()
    startRecorder(stream, cb)
    const [recorder] = FakeMediaRecorder.instances
    expect(recorder.timeslice).toBe(CHUNK_EVERY_MS)

    await advance(0)
    expect(cb.onStart).toHaveBeenCalledTimes(1)

    recorder.emit('one')
    recorder.emit('two')
    expect(cb.onChunk).toHaveBeenCalledTimes(2)
    expect(await (cb.onChunk.mock.calls[0][0] as Blob).text()).toBe('one')
  })

  it('cuts the first piece after 2 seconds, so the server sees a real recording almost at once', async () => {
    startRecorder(stream, callbacks())
    const [recorder] = FakeMediaRecorder.instances
    await advance(FIRST_CHUNK_AFTER_MS - 1)
    expect(recorder.requestedData).toBe(0)
    await advance(1)
    expect(recorder.requestedData).toBe(1)
  })

  it('ignores an empty piece', () => {
    const cb = callbacks()
    startRecorder(stream, cb)
    FakeMediaRecorder.instances[0].ondataavailable?.({ data: new Blob([]) })
    expect(cb.onChunk).not.toHaveBeenCalled()
  })

  it('reports an error from the recorder, and a stop it was not asked for', () => {
    const cb = callbacks()
    startRecorder(stream, cb)
    const [recorder] = FakeMediaRecorder.instances
    recorder.onerror?.()
    recorder.end() // a track ended under it
    expect(cb.onError).toHaveBeenCalledTimes(1)
    expect(cb.onStop).toHaveBeenCalledTimes(1)
  })

  describe('stop()', () => {
    it('waits for the last piece, which is handed over before it resolves', async () => {
      const cb = callbacks()
      const running = startRecorder(stream, cb)
      await advance(0)

      await running.stop()

      expect(await (cb.onChunk.mock.calls.at(-1)![0] as Blob).text()).toBe('last')
      expect(running.isRecording()).toBe(false)
    })

    it('is safe on a recorder that has already stopped', async () => {
      const running = startRecorder(stream, callbacks())
      FakeMediaRecorder.instances[0].end()
      await expect(running.stop()).resolves.toBeUndefined()
    })

    it('does not cut a first piece after it has stopped', async () => {
      const running = startRecorder(stream, callbacks())
      await running.stop()
      const before = FakeMediaRecorder.instances[0].requestedData
      await advance(FIRST_CHUNK_AFTER_MS * 2)
      expect(FakeMediaRecorder.instances[0].requestedData).toBe(before)
    })

    it('gives up waiting if the browser never says it has stopped', async () => {
      const running = startRecorder(stream, callbacks())
      const [recorder] = FakeMediaRecorder.instances
      recorder.stop = () => undefined // stop() is called but nothing follows
      const done = vi.fn()
      void running.stop().then(done)
      await advance(4_999)
      expect(done).not.toHaveBeenCalled()
      await advance(2)
      expect(done).toHaveBeenCalled()
    })
  })

  it('says plainly when the browser cannot record at all', () => {
    vi.unstubAllGlobals()
    expect(recorderSupported()).toBe(false)
    expect(() => startRecorder(stream, callbacks())).toThrow(RecorderUnsupportedError)
  })
})
