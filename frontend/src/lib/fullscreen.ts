// Full screen, as the exam uses it. A browser only allows entering full screen from a click or a
// key press, so `enterFullscreen` must be called from one. A page cannot stop the candidate
// leaving (Esc, F11, Alt+Tab); it can only notice and show a cover until they return.

export function fullscreenSupported(): boolean {
  return typeof document !== 'undefined' && document.fullscreenEnabled === true
}

export function isFullscreen(): boolean {
  return typeof document !== 'undefined' && document.fullscreenElement != null
}

/** True when the browser agreed. Call it from a click handler. */
export async function enterFullscreen(): Promise<boolean> {
  try {
    await document.documentElement.requestFullscreen({ navigationUI: 'hide' })
    return true
  } catch {
    return false
  }
}

export async function leaveFullscreen(): Promise<void> {
  if (!isFullscreen()) return
  try {
    await document.exitFullscreen()
  } catch {
    // already out, or the browser refused: nothing to do
  }
}

/** Calls back with the new state whenever it changes. Returns the function that stops listening. */
export function onFullscreenChange(callback: (full: boolean) => void): () => void {
  const handler = () => callback(isFullscreen())
  document.addEventListener('fullscreenchange', handler)
  return () => document.removeEventListener('fullscreenchange', handler)
}
