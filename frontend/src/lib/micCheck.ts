// The pre-check's microphone test as a pure state machine: the candidate says their name, and the
// check passes once the level has been above a small threshold for one second in total within
// ten seconds. The time is cumulative, not unbroken, because speech has gaps between words and a
// check that restarts on every pause would block honest candidates at the gate. A muted track
// never gets this far (the screen passes level 0 when `micMuted()`).
//
// `speechRms` is a starting value: it sits above the noise floor of a live microphone and below
// a normal speaking voice with automatic gain off. Tune it from D2 check 12 (master plan 7.8).

export interface MicCheckConfig {
  speechRms: number // level that counts as someone speaking
  holdMs: number // total time above that level needed to pass
  limitMs: number // give up after this long
}

export const MIC_CHECK: MicCheckConfig = { speechRms: 0.005, holdMs: 1000, limitMs: 10_000 }

export type MicCheckResult = 'listening' | 'passed' | 'failed'

export interface MicCheckState {
  elapsedMs: number
  heldMs: number
  result: MicCheckResult
}

export const INITIAL_MIC_CHECK: MicCheckState = { elapsedMs: 0, heldMs: 0, result: 'listening' }

export function stepMicCheck(
  state: MicCheckState,
  rms: number,
  dtMs: number,
  config: MicCheckConfig = MIC_CHECK,
): MicCheckState {
  if (state.result !== 'listening') return state
  const elapsedMs = state.elapsedMs + dtMs
  const heldMs = rms >= config.speechRms ? state.heldMs + dtMs : state.heldMs
  if (heldMs >= config.holdMs) return { elapsedMs, heldMs, result: 'passed' }
  if (elapsedMs >= config.limitMs) return { elapsedMs, heldMs, result: 'failed' }
  return { elapsedMs, heldMs, result: 'listening' }
}
