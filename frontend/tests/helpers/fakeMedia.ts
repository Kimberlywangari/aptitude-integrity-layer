import { vi } from 'vitest'
import type { DeviceHandle } from '../../src/lib/devices'

// Stand-ins for the browser's recorder and for a camera and microphone, which jsdom does not have.
//   vi.stubGlobal('MediaRecorder', FakeMediaRecorder)

export class FakeMediaRecorder {
  static instances: FakeMediaRecorder[] = []
  static supported = true
  static isTypeSupported = vi.fn((type: string) => FakeMediaRecorder.supported && type.includes('vp8'))

  static reset(): void {
    FakeMediaRecorder.instances = []
    FakeMediaRecorder.supported = true
    FakeMediaRecorder.isTypeSupported.mockClear()
  }

  state: 'inactive' | 'recording' = 'inactive'
  timeslice: number | undefined
  requestedData = 0
  ondataavailable: ((event: { data: Blob }) => void) | null = null
  onstart: (() => void) | null = null
  onerror: (() => void) | null = null
  onstop: (() => void) | null = null
  private stopListeners: (() => void)[] = []

  constructor(
    public stream: MediaStream,
    public options: Record<string, unknown>,
  ) {
    FakeMediaRecorder.instances.push(this)
  }

  start(timeslice?: number): void {
    this.state = 'recording'
    this.timeslice = timeslice
    queueMicrotask(() => this.onstart?.())
  }

  /** The browser handing over a piece. */
  emit(text: string): void {
    this.ondataavailable?.({ data: new Blob([text]) })
  }

  requestData(): void {
    this.requestedData += 1
    this.emit(`requested-${this.requestedData}`)
  }

  addEventListener(type: string, listener: () => void): void {
    if (type === 'stop') this.stopListeners.push(listener)
  }

  /** What stop() does: the last piece, then "stopped". */
  stop(): void {
    if (this.state === 'inactive') throw new DOMException('not recording', 'InvalidStateError')
    this.emit('last')
    this.end()
  }

  /** The recorder stopping by itself, because a track ended under it. */
  end(): void {
    this.state = 'inactive'
    this.onstop?.()
    this.stopListeners.forEach((listener) => listener())
  }
}

export class FakeTrack extends EventTarget {
  readyState: 'live' | 'ended' = 'live'
  stopped = false
  /** The device going away (unplugged, taken by another program). */
  end(): void {
    this.readyState = 'ended'
    this.dispatchEvent(new Event('ended'))
  }
  stop(): void {
    this.stopped = true
    this.readyState = 'ended' // stopping a track does not announce itself
  }
}

export interface FakeDevices {
  handle: DeviceHandle
  video: FakeTrack
  audio: FakeTrack
  stop: ReturnType<typeof vi.fn>
  setPeak(peak: number): void
  setMuted(muted: boolean): void
}

export function fakeDevices(labels = { camera: 'Integrated Camera', mic: 'Headset Microphone' }): FakeDevices {
  const video = new FakeTrack()
  const audio = new FakeTrack()
  let peak = 0.05
  let muted = false
  const stop = vi.fn()
  const handle: DeviceHandle = {
    stream: {
      getVideoTracks: () => [video],
      getAudioTracks: () => [audio],
      getTracks: () => [video, audio],
    } as unknown as MediaStream,
    cameraLabel: labels.camera,
    micLabel: labels.mic,
    videoSize: { width: 320, height: 240 },
    micMuted: () => muted,
    readMicLevel: () => ({ rms: peak / 4, peak }),
    stop,
  }
  return {
    handle,
    video,
    audio,
    stop,
    setPeak: (value) => {
      peak = value
    },
    setMuted: (value) => {
      muted = value
    },
  }
}
