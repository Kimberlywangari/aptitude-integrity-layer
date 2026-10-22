import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { logEvent } from '../src/lib/eventLog'
import type { DeviceHandle } from '../src/lib/devices'
import { holdDevices, releaseDevices } from '../src/lib/media'
import {
  INITIAL_MIC_WATCH,
  MIC_FLAT_PEAK,
  MIC_RECOVER_MS,
  MIC_SILENCE_MS,
  startMicWatch,
  stepMicWatch,
} from '../src/lib/micWatch'
import type { MicWatchEffect, MicWatchState } from '../src/lib/micWatch'
import { getMicSilent, setMicSilent } from '../src/lib/micStatus'

vi.mock('../src/lib/eventLog', () => ({ logEvent: vi.fn(() => Promise.resolve()) }))

const LOUD = 0.05
const FLAT = 0

/** Feeds readings one second apart. Returns the final state and every effect along the way. */
function run(readings: { peak: number; muted?: boolean }[], from = 0) {
  let state: MicWatchState = INITIAL_MIC_WATCH
  const effects: MicWatchEffect[] = []
  readings.forEach((reading, i) => {
    const step = stepMicWatch(state, { peak: reading.peak, muted: reading.muted ?? false, now: from + i * 1000 })
    state = step.state
    effects.push(...step.effects)
  })
  return { state, effects }
}

const seconds = (count: number, peak: number, muted = false) =>
  Array.from({ length: count }, () => ({ peak, muted }))

describe('stepMicWatch()', () => {
  it('says nothing about a microphone that is hearing something', () => {
    const { state, effects } = run(seconds(300, LOUD))
    expect(effects).toEqual([])
    expect(state.silent).toBe(false)
  })

  it('waits a full minute of flat signal before calling it silent', () => {
    expect(run(seconds(60, FLAT)).effects).toEqual([]) // readings at 0 s .. 59 s
    expect(run(seconds(61, FLAT)).effects).toHaveLength(1) // the one at 60 s
  })

  it('dates the start to when the quiet began, not to when it was noticed', () => {
    const { effects } = run([...seconds(5, LOUD), ...seconds(70, FLAT)])
    expect(effects).toEqual([{ kind: 'start', at: 5_000 }])
  })

  it('counts a muted track as flat even if a level comes through', () => {
    expect(run(seconds(61, LOUD, true)).effects).toEqual([{ kind: 'start', at: 0 }])
  })

  it('forgets a quiet spell that sound interrupted in time', () => {
    const { effects } = run([...seconds(50, FLAT), ...seconds(1, LOUD), ...seconds(50, FLAT)])
    expect(effects).toEqual([])
  })

  it('treats the level threshold as flat below it and not flat at it', () => {
    expect(run(seconds(61, MIC_FLAT_PEAK - 1e-6)).effects).toHaveLength(1)
    expect(run(seconds(61, MIC_FLAT_PEAK)).effects).toEqual([])
  })

  describe('once silent', () => {
    const silent = [...seconds(61, FLAT)] // silent since 0 s

    it('ends only after sound has been back for a second', () => {
      const { effects } = run([...silent, ...seconds(1, LOUD)])
      expect(effects.map((e) => e.kind)).toEqual(['start']) // one reading is not a second yet

      const done = run([...silent, ...seconds(2, LOUD)])
      expect(done.effects.map((e) => e.kind)).toEqual(['start', 'end'])
    })

    it('reports how long it lasted, up to the moment sound returned', () => {
      const { effects } = run([...silent, ...seconds(3, LOUD)])
      expect(effects.at(-1)).toEqual({ kind: 'end', durationS: 61 })
    })

    it('does not end on a blip: sound has to be back for a second, unbroken', () => {
      const { effects, state } = run([...silent, ...seconds(1, LOUD), ...seconds(1, FLAT), ...seconds(1, LOUD)])
      expect(effects.map((e) => e.kind)).toEqual(['start'])
      expect(state.silent).toBe(true)
    })

    it('can go silent again afterwards, and say so again', () => {
      const { effects } = run([...silent, ...seconds(3, LOUD), ...seconds(65, FLAT)])
      expect(effects.map((e) => e.kind)).toEqual(['start', 'end', 'start'])
    })
  })

  it('uses the constants the plan names', () => {
    expect(MIC_SILENCE_MS).toBe(60_000)
    expect(MIC_RECOVER_MS).toBe(1_000)
  })
})

describe('mic watch', () => {
  let peak = LOUD
  let muted = false
  let stop: () => void

  const handle = {
    stream: {} as MediaStream,
    cameraLabel: '',
    micLabel: '',
    videoSize: { width: 0, height: 0 },
    micMuted: () => muted,
    readMicLevel: () => ({ rms: peak / 4, peak }),
    stop: vi.fn(),
  } as DeviceHandle

  beforeEach(() => {
    vi.useFakeTimers({ toFake: ['setInterval', 'clearInterval', 'performance'] })
    vi.mocked(logEvent).mockClear()
    peak = LOUD
    muted = false
    setMicSilent(false)
    holdDevices(handle)
    stop = startMicWatch()
  })

  afterEach(() => {
    stop()
    releaseDevices()
    vi.useRealTimers()
  })

  it('shows the banner and logs after a minute of silence, then clears both when sound returns', () => {
    peak = FLAT
    vi.advanceTimersByTime(MIC_SILENCE_MS + 2_000)
    expect(getMicSilent()).toBe(true)
    const [type, payload, options] = vi.mocked(logEvent).mock.calls[0]
    expect(type).toBe('mic_silent_start')
    expect(payload).toBeUndefined()
    expect(options?.at).toBeLessThan(2_000) // dated to when the quiet began

    peak = LOUD
    vi.advanceTimersByTime(2_000)
    expect(getMicSilent()).toBe(false)
    const end = vi.mocked(logEvent).mock.calls.at(-1)!
    expect(end[0]).toBe('mic_silent_end')
    expect((end[1] as { duration_s: number }).duration_s).toBeGreaterThan(59)
  })

  it('uses a physical mute too, whatever level comes through', () => {
    muted = true
    vi.advanceTimersByTime(MIC_SILENCE_MS + 2_000)
    expect(getMicSilent()).toBe(true)
  })

  it('does not mistake one quiet instant between sounds for a silent microphone', () => {
    // a reading is taken every 250 ms; quiet only every fourth time is not a flat second
    let n = 0
    handle.readMicLevel = () => ({ rms: 0, peak: n++ % 4 === 0 ? FLAT : LOUD })
    vi.advanceTimersByTime(MIC_SILENCE_MS * 2)
    expect(getMicSilent()).toBe(false)
    handle.readMicLevel = () => ({ rms: peak / 4, peak })
  })

  it('judges nothing while there is no stream to judge (the camera is being reconnected)', () => {
    releaseDevices()
    peak = FLAT
    vi.advanceTimersByTime(MIC_SILENCE_MS * 2)
    expect(getMicSilent()).toBe(false)
    expect(logEvent).not.toHaveBeenCalled()
  })

  it('clears the banner when it stops', () => {
    peak = FLAT
    vi.advanceTimersByTime(MIC_SILENCE_MS + 2_000)
    expect(getMicSilent()).toBe(true)
    stop()
    expect(getMicSilent()).toBe(false)
  })
})
