// One run of the browser's recorder on the camera and microphone stream. A "segment" is one such
// run: it starts with its own container header, which is why the server keeps segments apart. A
// camera that drops mid-test ends one run and a later reconnect starts the next.
//
// Sizes follow the capture spike: 150 + 24 kbit/s at 320x240 is about 80 MB an hour at most, which
// a candidate on a weak connection can carry. The first chunk is cut after 2 s so the server sees a
// real recording (and opens its gate) within moments; the rest follow every 10 s.

export const RECORDER_MIME = 'video/webm;codecs=vp8,opus'
export const VIDEO_BITS_PER_SECOND = 150_000
export const AUDIO_BITS_PER_SECOND = 24_000
export const CHUNK_EVERY_MS = 10_000
export const FIRST_CHUNK_AFTER_MS = 2_000
const STOP_WAIT_MS = 5_000

export class RecorderUnsupportedError extends Error {
  constructor() {
    super('this browser cannot record')
  }
}

export interface RecorderCallbacks {
  /** Recording has really begun: the moment the server uses to place a flag in the video. */
  onStart(): void
  /** A piece of the recording, in order. */
  onChunk(blob: Blob): void
  /** The recorder failed on its own. */
  onError(): void
  /** It stopped, whether asked to or because a track ended. */
  onStop(): void
}

export interface RunningRecorder {
  isRecording(): boolean
  /** Stops and waits for the last piece. Safe to call on a recorder that has already stopped. */
  stop(): Promise<void>
}

export function recorderSupported(): boolean {
  return typeof MediaRecorder !== 'undefined'
}

export function startRecorder(stream: MediaStream, callbacks: RecorderCallbacks): RunningRecorder {
  if (!recorderSupported()) throw new RecorderUnsupportedError()
  const mimeType = MediaRecorder.isTypeSupported?.(RECORDER_MIME) ? RECORDER_MIME : 'video/webm'
  const recorder = new MediaRecorder(stream, {
    mimeType,
    videoBitsPerSecond: VIDEO_BITS_PER_SECOND,
    audioBitsPerSecond: AUDIO_BITS_PER_SECOND,
  })

  recorder.ondataavailable = (event) => {
    if (event.data && event.data.size > 0) callbacks.onChunk(event.data)
  }
  recorder.onstart = () => callbacks.onStart()
  recorder.onerror = () => callbacks.onError()
  recorder.onstop = () => callbacks.onStop()

  recorder.start(CHUNK_EVERY_MS)
  const firstChunk = window.setTimeout(() => {
    if (recorder.state === 'recording') recorder.requestData()
  }, FIRST_CHUNK_AFTER_MS)

  return {
    isRecording: () => recorder.state === 'recording',
    stop: () =>
      new Promise<void>((resolve) => {
        window.clearTimeout(firstChunk)
        if (recorder.state === 'inactive') return resolve()
        const giveUp = window.setTimeout(resolve, STOP_WAIT_MS)
        recorder.addEventListener(
          'stop',
          () => {
            window.clearTimeout(giveUp)
            resolve()
          },
          { once: true },
        )
        try {
          recorder.stop()
        } catch {
          window.clearTimeout(giveUp)
          resolve()
        }
      }),
  }
}
