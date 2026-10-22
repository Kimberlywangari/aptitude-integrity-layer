// The recording for one test, start to finish. It owns the recorder, notices when the camera or
// microphone is lost, and carries on with a new segment when they come back. The test itself never
// stops for any of this: a lost camera shows a banner and the clock keeps running (the server's
// clock is what counts).
//
//   start      -> device_info, recording_started {segment 0}
//   a track ends -> track_ended {kind}; "lost"; a new attempt every 5 s
//   it returns  -> a new segment: recording_started {segment n}, camera_dropped {duration_s}
//   stop       -> the last chunk is flushed and counted, and the number goes to `finish`
//
// A chunk is numbered and stored the moment it arrives (chunkQueue) and the uploader sends it; this
// file never talks to the server itself.

import { addChunk, chunksTotal, nextSegment } from './chunkQueue'
import { acquireDevices } from './devices'
import type { DeviceHandle } from './devices'
import { logEvent } from './eventLog'
import { heldDevices, holdDevices, releaseDevices } from './media'
import { RecorderUnsupportedError, recorderSupported, startRecorder } from './recorder'
import type { RunningRecorder } from './recorder'
import { getSessionId } from './session'
import { wakeUploader } from './uploader'

export { RecorderUnsupportedError }

export type RecordingState = 'off' | 'starting' | 'recording' | 'lost'

export const RECONNECT_EVERY_MS = 5_000

let state: RecordingState = 'off'
let sessionId: string | null = null
let recorder: RunningRecorder | null = null
let generation = 0 // each recorder run has its own; callbacks from an older run are ignored
let intake: Promise<void> = Promise.resolve()
let retryTimer: number | undefined
let lostAt: number | null = null
let trackCleanups: (() => void)[] = []
const listeners = new Set<() => void>()

function setState(next: RecordingState): void {
  if (state === next) return
  state = next
  listeners.forEach((listener) => listener())
}

export function recordingState(): RecordingState {
  return state
}

export function onRecordingState(listener: () => void): () => void {
  listeners.add(listener)
  return () => {
    listeners.delete(listener)
  }
}

/** Numbers and stores a chunk. In order, one at a time, so numbers follow the order of arrival. */
function enqueue(id: string, segment: number, blob: Blob): void {
  intake = intake
    .then(async () => {
      await addChunk(id, segment, blob)
      wakeUploader()
    })
    .catch(() => undefined) // a chunk that cannot be stored shows up as missing, not as a crash
}

function unwatchTracks(): void {
  trackCleanups.forEach((cleanup) => cleanup())
  trackCleanups = []
}

function watchTracks(handle: DeviceHandle): void {
  unwatchTracks()
  const video = handle.stream.getVideoTracks()[0]
  const audio = handle.stream.getAudioTracks()[0]
  const on = (track: MediaStreamTrack | undefined, type: string, handler: () => void) => {
    track?.addEventListener(type, handler)
    trackCleanups.push(() => track?.removeEventListener(type, handler))
  }
  on(video, 'ended', () => lose('video'))
  on(audio, 'ended', () => lose('audio'))
  on(audio, 'mute', () => void logEvent('mic_muted'))
  on(audio, 'unmute', () => void logEvent('mic_unmuted'))
}

async function beginSegment(handle: DeviceHandle): Promise<void> {
  const id = sessionId
  if (!id) return
  const segment = await nextSegment(id)
  const mine = ++generation
  watchTracks(handle)
  recorder = startRecorder(handle.stream, {
    onStart: () => {
      if (mine !== generation) return
      void logEvent('recording_started', { segment })
      setState('recording')
    },
    // always kept, even from a run that has just been replaced: it is the last of its data
    onChunk: (blob) => enqueue(id, segment, blob),
    onError: () => {
      if (mine === generation) lose('recorder')
    },
    onStop: () => {
      // it stopped without being asked to: a track ended under it
      if (mine === generation && state === 'recording') lose('recorder')
    },
  })
}

function scheduleReconnect(): void {
  window.clearTimeout(retryTimer)
  retryTimer = window.setTimeout(() => void reconnect(), RECONNECT_EVERY_MS)
}

function lose(kind: string): void {
  if (state !== 'recording' && state !== 'starting') return
  lostAt = performance.now()
  void logEvent('track_ended', { kind })
  setState('lost')
  const old = recorder
  recorder = null
  generation += 1
  unwatchTracks()
  void old?.stop() // hands over whatever it still holds
  releaseDevices()
  scheduleReconnect()
}

async function reconnect(): Promise<void> {
  if (state !== 'lost' || !sessionId) return
  let handle: DeviceHandle | null = null
  try {
    handle = await acquireDevices()
    holdDevices(handle)
    setState('starting')
    await beginSegment(handle)
    const gapS = lostAt === null ? 0 : (performance.now() - lostAt) / 1000
    void logEvent('camera_dropped', { duration_s: gapS }, { at: lostAt ?? undefined })
    lostAt = null
  } catch {
    handle?.stop()
    if (heldDevices() === handle) releaseDevices()
    setState('lost')
    scheduleReconnect()
  }
}

/**
 * Starts recording on a stream the pre-check (or a reconnect) already holds. Resolves when the
 * recorder has been asked to start; `recording` is reported through the state when it really has.
 * Throws RecorderUnsupportedError in a browser that cannot record.
 */
export async function startRecording(id: string, handle: DeviceHandle): Promise<void> {
  if (state === 'recording' || state === 'starting') return
  if (!recorderSupported()) throw new RecorderUnsupportedError()
  sessionId = id
  setState('starting')
  holdDevices(handle)
  void logEvent('device_info', { camera_label: handle.cameraLabel, mic_label: handle.micLabel })
  try {
    await beginSegment(handle)
  } catch (error) {
    setState('off')
    throw error
  }
}

/**
 * For a page that finds itself mid-test with no stream (after a reload the stream is gone): ask for
 * the camera again and carry on in a new segment. If it cannot be had, the banner shows and the
 * attempts continue every 5 s.
 */
export async function ensureRecording(id: string): Promise<void> {
  if (state !== 'off') return
  sessionId = id
  try {
    await startRecording(id, heldDevices() ?? (await acquireDevices()))
  } catch {
    lostAt = performance.now()
    setState('lost')
    scheduleReconnect()
  }
}

/**
 * Ends the recording: stops the recorder, waits for its last chunk to be stored, lets the camera
 * go, and returns how many chunks the session has made, which is what `finish` must be told.
 */
export async function stopRecording(): Promise<number> {
  const id = sessionId ?? getSessionId()
  window.clearTimeout(retryTimer)
  generation += 1 // from here on no run's start, stop or error means anything
  unwatchTracks()
  const running = recorder
  recorder = null
  await running?.stop()
  await intake // chunks still being numbered and stored
  releaseDevices()
  setState('off')
  wakeUploader()
  return id ? chunksTotal(id) : 0
}

/** For tests. */
export function resetRecording(): void {
  window.clearTimeout(retryTimer)
  unwatchTracks()
  recorder = null
  generation = 0
  intake = Promise.resolve()
  lostAt = null
  sessionId = null
  state = 'off'
  listeners.clear()
}
