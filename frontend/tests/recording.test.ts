import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { nextSegment } from '../src/lib/chunkQueue'
import { acquireDevices } from '../src/lib/devices'
import { logEvent } from '../src/lib/eventLog'
import { heldDevices, releaseDevices } from '../src/lib/media'
import {
  RECONNECT_EVERY_MS,
  RecorderUnsupportedError,
  ensureRecording,
  onRecordingState,
  recordingState,
  resetRecording,
  startRecording,
  stopRecording,
} from '../src/lib/recording'
import { clearSession, saveSession } from '../src/lib/session'
import { createMemoryStore, setStore } from '../src/lib/store'
import type { DeviceStore } from '../src/lib/store'
import { wakeUploader } from '../src/lib/uploader'
import { FakeMediaRecorder, fakeDevices } from './helpers/fakeMedia'

vi.mock('../src/lib/devices', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../src/lib/devices')>()),
  acquireDevices: vi.fn(),
}))
vi.mock('../src/lib/eventLog', () => ({ logEvent: vi.fn(() => Promise.resolve()) }))
vi.mock('../src/lib/uploader', () => ({ wakeUploader: vi.fn() }))

const advance = (ms: number) => vi.advanceTimersByTimeAsync(ms)
async function flush(ms = 0) {
  await advance(ms)
  for (let i = 0; i < 6; i++) await advance(0)
}

const events = () => vi.mocked(logEvent).mock.calls.map((call) => [call[0], call[1]])
const recorders = () => FakeMediaRecorder.instances

// Hashing a chunk uses the browser's real asynchronous crypto, which a fake clock cannot move, so
// wait for the chunks themselves instead of counting turns of the event loop.
async function storedChunks(store: DeviceStore, count: number) {
  await vi.waitFor(async () => expect(await store.chunks('s1')).toHaveLength(count))
  return (await store.chunks('s1')).map((c) => [c.seq, c.segment, c.status])
}

describe('recording', () => {
  let store: DeviceStore

  beforeEach(() => {
    vi.useFakeTimers({ toFake: ['setTimeout', 'clearTimeout', 'setInterval', 'clearInterval', 'performance'] })
    vi.stubGlobal('MediaRecorder', FakeMediaRecorder)
    FakeMediaRecorder.reset()
    vi.mocked(logEvent).mockClear()
    vi.mocked(wakeUploader).mockClear()
    vi.mocked(acquireDevices).mockReset()
    sessionStorage.clear()
    store = createMemoryStore()
    setStore(store)
    releaseDevices()
    resetRecording()
    saveSession('s1', 'tok')
  })

  afterEach(async () => {
    await stopRecording()
    resetRecording()
    releaseDevices()
    vi.useRealTimers()
    vi.unstubAllGlobals()
    clearSession()
  })

  describe('starting', () => {
    it('records the devices, starts segment 0 and logs the moment recording really began', async () => {
      const d = fakeDevices()
      const states: string[] = []
      onRecordingState(() => states.push(recordingState()))

      await startRecording('s1', d.handle)
      await flush()

      expect(events()).toEqual([
        ['device_info', { camera_label: 'Integrated Camera', mic_label: 'Headset Microphone' }],
        ['recording_started', { segment: 0 }],
      ])
      expect(states).toEqual(['starting', 'recording'])
      expect(heldDevices()).toBe(d.handle)
      expect(recorders()).toHaveLength(1)
    })

    it('is a no-op if it is already recording', async () => {
      const d = fakeDevices()
      await startRecording('s1', d.handle)
      await flush()
      await startRecording('s1', fakeDevices().handle)
      expect(recorders()).toHaveLength(1)
    })

    it('says so, and leaves nothing behind, in a browser that cannot record', async () => {
      vi.unstubAllGlobals()
      await expect(startRecording('s1', fakeDevices().handle)).rejects.toThrow(RecorderUnsupportedError)
      expect(recordingState()).toBe('off')
      expect(events()).toEqual([])
    })
  })

  describe('the chunks', () => {
    it('are numbered and kept in the order they arrive, then the uploader is woken', async () => {
      await startRecording('s1', fakeDevices().handle)
      await flush()

      recorders()[0].emit('first')
      recorders()[0].emit('second')

      expect(await storedChunks(store, 2)).toEqual([
        [0, 0, 'pending'],
        [1, 0, 'pending'],
      ])
      expect(wakeUploader).toHaveBeenCalled()
    })
  })

  describe('stopping', () => {
    it('keeps the last piece, counts every chunk, lets the camera go and reports the total', async () => {
      const d = fakeDevices()
      await startRecording('s1', d.handle)
      await flush()
      recorders()[0].emit('a')
      recorders()[0].emit('b')

      const total = await stopRecording()

      expect(total).toBe(3) // a, b and the last piece the recorder gave on stopping
      expect((await storedChunks(store, 3)).map((c) => c[0])).toEqual([0, 1, 2])
      expect(d.stop).toHaveBeenCalled()
      expect(heldDevices()).toBeNull()
      expect(recordingState()).toBe('off')
      expect(wakeUploader).toHaveBeenCalled()
    })

    it('knows the total after a reload, when there is nothing running to stop', async () => {
      await store.nextCounter('chunks:s1')
      await store.nextCounter('chunks:s1')
      await store.nextCounter('chunks:s1')
      expect(await stopRecording()).toBe(3)
    })

    it('reports 0 when nothing was ever recorded', async () => {
      expect(await stopRecording()).toBe(0)
    })

    it('no longer minds a track ending once it has stopped', async () => {
      const d = fakeDevices()
      await startRecording('s1', d.handle)
      await flush()
      await stopRecording()
      vi.mocked(logEvent).mockClear()

      d.video.end()
      await flush()
      expect(events()).toEqual([])
      expect(recordingState()).toBe('off')
    })
  })

  describe('the microphone being muted', () => {
    it('is logged when the track says so, and when it says it is back', async () => {
      const d = fakeDevices()
      await startRecording('s1', d.handle)
      await flush()
      vi.mocked(logEvent).mockClear()

      d.audio.dispatchEvent(new Event('mute'))
      d.audio.dispatchEvent(new Event('unmute'))

      expect(events()).toEqual([['mic_muted', undefined], ['mic_unmuted', undefined]])
    })
  })

  describe('when the camera is lost', () => {
    it.each(['video', 'audio'] as const)('notices a %s track ending, says so and shows it', async (kind) => {
      const d = fakeDevices()
      await startRecording('s1', d.handle)
      await flush()
      vi.mocked(logEvent).mockClear()

      d[kind].end()
      await flush()

      expect(events()).toEqual([['track_ended', { kind }]])
      expect(recordingState()).toBe('lost')
      expect(heldDevices()).toBeNull()
      expect(d.stop).toHaveBeenCalled() // the dead stream is let go
    })

    it('still keeps what the recorder had when the track ended', async () => {
      const d = fakeDevices()
      await startRecording('s1', d.handle)
      await flush()
      recorders()[0].emit('before the drop')

      d.video.end()

      expect((await storedChunks(store, 2)).map((c) => [c[0], c[1]])).toEqual([
        [0, 0],
        [1, 0], // the last piece, handed over as it stopped
      ])
    })

    it('tries again every 5 seconds, quietly, until the camera is back', async () => {
      const d = fakeDevices()
      await startRecording('s1', d.handle)
      await flush()
      d.video.end()
      await flush()

      vi.mocked(acquireDevices).mockRejectedValue(new DOMException('in use', 'NotReadableError'))
      await flush(RECONNECT_EVERY_MS)
      await flush(RECONNECT_EVERY_MS)
      expect(acquireDevices).toHaveBeenCalledTimes(2)
      expect(recordingState()).toBe('lost')

      const back = fakeDevices()
      vi.mocked(acquireDevices).mockResolvedValue(back.handle)
      await flush(RECONNECT_EVERY_MS)
      expect(acquireDevices).toHaveBeenCalledTimes(3)
      expect(recordingState()).toBe('recording')
      expect(heldDevices()).toBe(back.handle)
    })

    it('carries on in a new segment, numbering chunks on from where it left off, and logs the gap', async () => {
      const d = fakeDevices()
      await startRecording('s1', d.handle)
      await flush()
      recorders()[0].emit('one')
      d.video.end() // chunks 0 and 1 (the second is the last piece)
      await flush()
      vi.mocked(logEvent).mockClear()

      const back = fakeDevices()
      vi.mocked(acquireDevices).mockResolvedValue(back.handle)
      await flush(RECONNECT_EVERY_MS)

      expect(recorders()).toHaveLength(2)
      const names = events().map((e) => e[0])
      expect(names).toContain('recording_started')
      expect(events()).toContainEqual(['recording_started', { segment: 1 }])
      const gap = vi.mocked(logEvent).mock.calls.find((call) => call[0] === 'camera_dropped')!
      expect((gap[1] as { duration_s: number }).duration_s).toBeCloseTo(5, 0)
      expect(gap[2]?.at).toBeDefined() // dated to when it was lost, not to when it came back

      recorders()[1].emit('after')
      expect((await storedChunks(store, 3)).map((c) => [c[0], c[1]])).toEqual([
        [0, 0],
        [1, 0],
        [2, 1],
      ])
    })

    it('stops trying when the recording is ended', async () => {
      const d = fakeDevices()
      await startRecording('s1', d.handle)
      await flush()
      d.video.end()
      await flush()

      await stopRecording()
      vi.mocked(acquireDevices).mockResolvedValue(fakeDevices().handle)
      await flush(RECONNECT_EVERY_MS * 3)
      expect(acquireDevices).not.toHaveBeenCalled()
    })
  })

  describe('ensureRecording() after a reload, when the stream is gone', () => {
    it('asks for the camera again and carries on in the next segment', async () => {
      await nextSegment('s1') // segment 0 belonged to the page life before the reload
      const back = fakeDevices()
      vi.mocked(acquireDevices).mockResolvedValue(back.handle)

      await ensureRecording('s1')
      await flush()

      expect(events()).toContainEqual(['recording_started', { segment: 1 }])
      expect(recordingState()).toBe('recording')
    })

    it('shows the banner and keeps trying if the camera cannot be had', async () => {
      vi.mocked(acquireDevices).mockRejectedValue(new DOMException('blocked', 'NotAllowedError'))
      await ensureRecording('s1')
      expect(recordingState()).toBe('lost')

      const back = fakeDevices()
      vi.mocked(acquireDevices).mockResolvedValue(back.handle)
      await flush(RECONNECT_EVERY_MS)
      expect(recordingState()).toBe('recording')
    })

    it('uses a stream the page already holds instead of asking again', async () => {
      const d = fakeDevices()
      const { holdDevices } = await import('../src/lib/media')
      holdDevices(d.handle)

      await ensureRecording('s1')
      await flush()

      expect(acquireDevices).not.toHaveBeenCalled()
      expect(recordingState()).toBe('recording')
    })

    it('does nothing if a recording is already going', async () => {
      await startRecording('s1', fakeDevices().handle)
      await flush()
      await ensureRecording('s1')
      expect(recorders()).toHaveLength(1)
      expect(acquireDevices).not.toHaveBeenCalled()
    })
  })
})
