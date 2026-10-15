// Camera and microphone access for the pre-check. When the shared stream owner (lib/media.ts,
// D6 step 3) lands, `acquireDevices` is the one function to point at it; the pre-check screen
// only depends on the DeviceHandle shape.

export type DeviceErrorKind = 'denied' | 'not_found' | 'in_use' | 'unknown'

export interface DeviceHandle {
  stream: MediaStream
  cameraLabel: string
  micLabel: string
  videoSize: { width: number; height: number }
  /** True while the microphone track reports itself muted (hardware switch, OS privacy toggle). */
  micMuted(): boolean
  /** Level of the last moments of audio: RMS for the meter, peak for the report. */
  readMicLevel(): { rms: number; peak: number }
  stop(): void
}

export function classifyDeviceError(error: unknown): DeviceErrorKind {
  const name = error instanceof DOMException || error instanceof Error ? error.name : ''
  switch (name) {
    case 'NotAllowedError':
    case 'SecurityError':
      return 'denied'
    case 'NotFoundError':
    case 'OverconstrainedError':
      return 'not_found'
    case 'NotReadableError':
    case 'AbortError':
      return 'in_use'
    default:
      return 'unknown'
  }
}

export async function acquireDevices(): Promise<DeviceHandle> {
  // Low resolution on purpose (measured about 40 to 50 MB an hour, 80 at most), and no audio
  // processing, so a live microphone keeps a faint noise floor and a muted one stays flat
  // (master plan 7.8).
  const stream = await navigator.mediaDevices.getUserMedia({
    video: { width: 320, height: 240, frameRate: 15 },
    audio: { echoCancellation: false, noiseSuppression: false, autoGainControl: false },
  })

  const video = stream.getVideoTracks()[0]
  const audio = stream.getAudioTracks()[0]
  const settings = video?.getSettings() ?? {}

  const context = new AudioContext()
  const analyser = context.createAnalyser()
  analyser.fftSize = 2048
  context.createMediaStreamSource(stream).connect(analyser)
  const samples = new Float32Array(analyser.fftSize)

  return {
    stream,
    cameraLabel: video?.label ?? '',
    micLabel: audio?.label ?? '',
    videoSize: { width: settings.width ?? 0, height: settings.height ?? 0 },
    micMuted: () => audio?.muted ?? true,
    readMicLevel: () => {
      analyser.getFloatTimeDomainData(samples)
      let sum = 0
      let peak = 0
      for (const value of samples) {
        sum += value * value
        peak = Math.max(peak, Math.abs(value))
      }
      return { rms: Math.sqrt(sum / samples.length), peak }
    },
    stop: () => {
      stream.getTracks().forEach((track) => track.stop())
      void context.close().catch(() => undefined)
    },
  }
}
