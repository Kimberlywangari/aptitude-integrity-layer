// The short notice on the test screen: "this has been recorded and a reviewer will see it".
//
// The server decides when it is due (the reply to a batch of events says `warn`), so the list of
// actions it covers lives with the flag rules and nowhere else. This only shows it, for a few
// seconds, and not more than once in a while: a burst of events must not flicker, and the notice
// must never get in the way of the question. It does not touch the clock.

import { ref } from 'vue'

export const SHOW_MS = 6_000
export const QUIET_MS = 20_000

export const noticeVisible = ref(false)

let hideTimer: ReturnType<typeof setTimeout> | undefined
let lastShown = -Infinity

export function noteRecorded(now: number = performance.now()): void {
  if (now - lastShown < QUIET_MS) return
  lastShown = now
  noticeVisible.value = true
  clearTimeout(hideTimer)
  hideTimer = setTimeout(() => {
    noticeVisible.value = false
  }, SHOW_MS)
}

/** For a new test, and for tests. */
export function clearNotice(): void {
  clearTimeout(hideTimer)
  noticeVisible.value = false
  lastShown = -Infinity
}
