// What the page sees the candidate do, turned into log events. It only listens: nothing is
// blocked or changed (the proposal says a web page cannot lock a computer, so a person decides what
// the log means).
//
// Copy and cut record how many characters were selected and nothing else. The text is never kept
// and never sent; the server drops anything but `length` as well.

import {
  onConnectionChange,
  reportBrowserOffline,
  reportBrowserOnline,
} from './connection'
import { logEvent } from './eventLog'
import { onFullscreenChange } from './fullscreen'

export const IDLE_AFTER_MS = 30_000
const IDLE_CHECK_MS = 1_000
const STARTED_FLAG = 'integrity.logger_started'

const ACTIVITY = ['mousemove', 'mousedown', 'keydown', 'wheel', 'scroll', 'touchstart', 'pointerdown']

let stopCurrent: (() => void) | null = null

function wasAlreadyRunning(): boolean {
  try {
    const was = sessionStorage.getItem(STARTED_FLAG) === '1'
    sessionStorage.setItem(STARTED_FLAG, '1')
    return was
  } catch {
    return false
  }
}

/** `reload` when this page was reloaded while the test was running; `page_load` otherwise. */
function loadKind(alreadyRunning: boolean): 'page_load' | 'reload' {
  const entry = performance.getEntriesByType?.('navigation')?.[0] as
    | PerformanceNavigationTiming
    | undefined
  return alreadyRunning && entry?.type === 'reload' ? 'reload' : 'page_load'
}

function selectedLength(): number {
  return window.getSelection()?.toString().length ?? 0
}

/** Starts logging. Returns the function that stops it. Starting twice does nothing the second time. */
export function startActionLogger(): () => void {
  if (stopCurrent) return stopCurrent

  void logEvent(loadKind(wasAlreadyRunning()))

  const listeners: [EventTarget, string, EventListener, AddEventListenerOptions?][] = []
  const on = (
    target: EventTarget,
    type: string,
    handler: EventListener,
    options?: AddEventListenerOptions,
  ) => {
    target.addEventListener(type, handler, options)
    listeners.push([target, type, handler, options])
  }

  // focus and visibility
  on(window, 'blur', () => void logEvent('focus_lost'))
  on(window, 'focus', () => void logEvent('focus_returned'))
  on(document, 'visibilitychange', () =>
    void logEvent(document.visibilityState === 'hidden' ? 'visibility_hidden' : 'visibility_visible'),
  )

  // clipboard and right-click: attempts, with a length for copy and cut and nothing else
  on(document, 'copy', () => void logEvent('copy_attempt', { length: selectedLength() }))
  on(document, 'cut', () => void logEvent('cut_attempt', { length: selectedLength() }))
  on(document, 'paste', () => void logEvent('paste_attempt'))
  on(document, 'contextmenu', () => void logEvent('contextmenu_attempt'))

  // the network
  on(window, 'offline', () => reportBrowserOffline())
  on(window, 'online', () => reportBrowserOnline())
  const stopConnection = onConnectionChange(
    ({ lost, since }) =>
      void logEvent(lost ? 'connection_lost' : 'connection_restored', undefined, { at: since }),
  )

  // full screen: context for the reviewer, never a flag
  const stopFullscreen = onFullscreenChange(
    (full) => void logEvent(full ? 'fullscreen_entered' : 'fullscreen_exited'),
  )

  // idle: nothing from the mouse, keyboard, wheel or touch for 30 s. The start is dated to when the
  // quiet began (30 s ago), not to when the next check noticed it.
  let lastActivity = performance.now()
  let idleSince: number | null = null
  const onActivity = () => {
    const now = performance.now()
    if (idleSince !== null) {
      void logEvent('idle_end', { duration_s: (now - idleSince) / 1000 })
      idleSince = null
    }
    lastActivity = now
  }
  for (const type of ACTIVITY) on(window, type, onActivity, { passive: true, capture: true })
  const idleTimer = window.setInterval(() => {
    if (idleSince === null && performance.now() - lastActivity >= IDLE_AFTER_MS) {
      idleSince = lastActivity + IDLE_AFTER_MS
      void logEvent('idle_start', undefined, { at: idleSince })
    }
  }, IDLE_CHECK_MS)

  stopCurrent = () => {
    for (const [target, type, handler, options] of listeners) {
      target.removeEventListener(type, handler, options)
    }
    stopConnection()
    stopFullscreen()
    window.clearInterval(idleTimer)
    stopCurrent = null
  }
  return stopCurrent
}
