// Whether the microphone currently looks muted or silent (master plan 7.8, layers 1 and 2).
// `micWatch` (D6) calls `setMicSilent`; MicBanner subscribes. A tiny external store keeps the
// banner free of any dependency on the recorder.

let silent = false
const listeners = new Set<() => void>()

export function setMicSilent(value: boolean): void {
  if (silent === value) return
  silent = value
  listeners.forEach((listener) => listener())
}

export function getMicSilent(): boolean {
  return silent
}

export function subscribeMicSilent(listener: () => void): () => void {
  listeners.add(listener)
  return () => {
    listeners.delete(listener)
  }
}
