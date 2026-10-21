// The live microphone watch (master plan 7.8, layer 2). A page cannot stop a candidate muting the
// microphone, so this notices and says so: after a minute of a flat signal or a muted track the
// candidate sees a banner asking them to unmute, and the log gets `mic_silent_start` and later
// `mic_silent_end`. It never blocks the test and never raises a flag; the stretches are context for
// the reviewer.
//
// Audio is requested with no processing (see devices.ts), so a live microphone in a quiet room
// keeps a faint noise floor and a muted one stays flat. MIC_FLAT_PEAK is the level below which a
// window counts as flat. It is a starting value, to be set against a real quiet room and a
// physically muted microphone (spike check 11).

import { logEvent } from './eventLog'
import { heldDevices } from './media'
import { setMicSilent } from './micStatus'

export const MIC_FLAT_PEAK = 0.0005
export const MIC_SILENCE_MS = 60_000
export const MIC_RECOVER_MS = 1_000
const READ_EVERY_MS = 250
const WINDOW_READINGS = 4 // the last second: one quiet instant is not a flat microphone

export interface MicWatchState {
  flatSince: number | null
  signalSince: number | null
  silentSince: number | null
  silent: boolean
}

export type MicWatchEffect =
  | { kind: 'start'; at: number }
  | { kind: 'end'; durationS: number }

export const INITIAL_MIC_WATCH: MicWatchState = {
  flatSince: null,
  signalSince: null,
  silentSince: null,
  silent: false,
}

/** One reading in, the new state and anything to log out. Pure, so it can be tested by the second. */
export function stepMicWatch(
  state: MicWatchState,
  reading: { peak: number; muted: boolean; now: number },
): { state: MicWatchState; effects: MicWatchEffect[] } {
  const { peak, muted, now } = reading
  const flat = muted || peak < MIC_FLAT_PEAK
  const effects: MicWatchEffect[] = []
  let next = { ...state }

  if (flat) {
    next.signalSince = null
    next.flatSince ??= now
    if (!next.silent && now - next.flatSince >= MIC_SILENCE_MS) {
      next.silent = true
      next.silentSince = next.flatSince // dated to when the quiet began, not when it was noticed
      effects.push({ kind: 'start', at: next.flatSince })
    }
  } else if (next.silent) {
    next.signalSince ??= now
    if (now - next.signalSince >= MIC_RECOVER_MS) {
      effects.push({ kind: 'end', durationS: (next.signalSince - (next.silentSince ?? now)) / 1000 })
      next = { ...INITIAL_MIC_WATCH }
    }
  } else {
    next.flatSince = null
  }
  return { state: next, effects }
}

let stopCurrent: (() => void) | null = null

/** Watches whatever microphone the page is holding. Returns the function that stops the watch. */
export function startMicWatch(): () => void {
  if (stopCurrent) return stopCurrent

  let state = INITIAL_MIC_WATCH
  const recent: number[] = []
  const timer = window.setInterval(() => {
    const handle = heldDevices()
    if (!handle) return // no stream (the camera is being reconnected): nothing to judge
    recent.push(handle.readMicLevel().peak)
    if (recent.length > WINDOW_READINGS) recent.shift()

    const result = stepMicWatch(state, {
      peak: Math.max(...recent),
      muted: handle.micMuted(),
      now: performance.now(),
    })
    state = result.state
    setMicSilent(state.silent)
    for (const effect of result.effects) {
      if (effect.kind === 'start') void logEvent('mic_silent_start', undefined, { at: effect.at })
      else void logEvent('mic_silent_end', { duration_s: effect.durationS })
    }
  }, READ_EVERY_MS)

  stopCurrent = () => {
    window.clearInterval(timer)
    setMicSilent(false)
    stopCurrent = null
  }
  return stopCurrent
}
