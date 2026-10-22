// The one camera and microphone the page holds. The pre-check asks for them once; the recording and
// the microphone watch then use the same stream through the whole test, so there is no second
// prompt and nothing to switch on again between screens. Whoever calls `releaseDevices` is the one
// ending it (the end of the recording, or the pre-check being left without passing).

import type { DeviceHandle } from './devices'

let held: DeviceHandle | null = null

/** Takes over a handle from the pre-check or from a reconnect. A different one held before is let go. */
export function holdDevices(handle: DeviceHandle): void {
  if (held && held !== handle) held.stop()
  held = handle
}

export function heldDevices(): DeviceHandle | null {
  return held
}

/** Stops the camera and microphone. */
export function releaseDevices(): void {
  held?.stop()
  held = null
}
