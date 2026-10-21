// The action log: what the candidate's page saw, kept on the device until the server has it.
//
// An event is written to the device store the moment it happens (so a reload or a closed tab
// loses nothing), then sent in batches. The page says how long ago each event happened (`age_ms`,
// worked out when it is sent) and the server subtracts that from its own clock, so an event held
// back by a dropped connection still lands at its true moment. Sending twice is safe: the server
// keeps one row per (session, client_seq).
//
// Logging must never get in the candidate's way, so nothing here throws and nothing is awaited by
// the test screens.

import { api, ApiError } from './api'
import type { EventIn, EventsResponse } from './api'
import { tracked } from './connection'
import { getSessionId } from './session'
import { getStore } from './store'
import type { StoredEvent } from './store'

const FLUSH_EVERY_MS = 2_000
const FLUSH_AT = 20
const BATCH = 100 // the server's limit per request
const BACKOFF_FIRST_MS = 1_000
const BACKOFF_MAX_MS = 60_000
const MAX_AGE_MS = 48 * 3_600 * 1_000 - 1 // the server refuses anything older

/** How long ago an event happened. Exact within one page life; across a reload the monotonic clock
 *  has restarted, so the wall clock is what is left. */
export function ageOf(event: Pick<StoredEvent, 'mono' | 'origin' | 'epoch'>): number {
  const sameLife = event.origin === (performance.timeOrigin ?? 0)
  const age = sameLife ? performance.now() - event.mono : Date.now() - event.epoch
  return Math.min(MAX_AGE_MS, Math.max(0, Math.round(age)))
}

interface LogOptions {
  /** performance.now() of the moment itself, for something noticed late (a long idle spell). */
  at?: number
}

let sessionId: string | null = null
let started = false
let halted = false // the server refused our token: stop trying until a new session starts
let failures = 0
let queued = 0
let timer: number | undefined
let writes: Promise<unknown> = Promise.resolve()
let sending: Promise<boolean> = Promise.resolve(true)
let removeListeners: (() => void) | null = null

function currentSession(): string | null {
  return sessionId ?? getSessionId()
}

/** Writes one event to the device. Never rejects, never needs awaiting. */
export function logEvent(
  type: string,
  payload?: Record<string, unknown>,
  options: LogOptions = {},
): Promise<void> {
  const id = currentSession()
  if (!id) return Promise.resolve()
  // the moment is fixed now, not when the (asynchronous) write gets its turn
  const mono = options.at ?? performance.now()
  const epoch = Date.now() - (performance.now() - mono)
  const origin = performance.timeOrigin ?? 0

  const write = writes
    .then(async () => {
      const store = await getStore()
      const seq = await store.nextCounter(`events:${id}`)
      await store.putEvent({ sessionId: id, seq, type, payload, mono, origin, epoch })
      queued += 1
      if (started && queued >= FLUSH_AT) void flushEvents()
    })
    .catch(() => undefined)
  writes = write
  return write
}

async function drain(keepalive: boolean): Promise<boolean> {
  const id = currentSession()
  if (!id || halted) return true
  await writes // an event logged a moment ago must be in this batch
  const store = await getStore()
  for (;;) {
    const stored = await store.events(id, BATCH)
    if (stored.length === 0) {
      queued = 0
      failures = 0
      return true
    }
    const events: EventIn[] = stored.map((event) => ({
      client_seq: event.seq,
      type: event.type.slice(0, 40),
      age_ms: ageOf(event),
      ...(event.payload ? { payload: event.payload } : {}),
    }))
    try {
      await tracked(() =>
        api<EventsResponse>('/api/events', { method: 'POST', body: { events }, keepalive }),
      )
    } catch (error) {
      if (error instanceof ApiError) {
        if (error.status === 401) {
          halted = true // a token that is not ours any more will never work
          return false
        }
        // A request the server refuses on its merits (a 4xx) would be refused again forever and
        // would hold up everything behind it, so it is dropped. Anything else is tried again.
        if (error.status >= 400 && error.status < 500 && error.status !== 408 && error.status !== 429) {
          await store.deleteEvents(id, stored.map((event) => event.seq))
          continue
        }
      }
      failures += 1
      return false
    }
    await store.deleteEvents(id, stored.map((event) => event.seq))
    failures = 0
    if (keepalive) return true // the page may be going; one batch is all there is time for
  }
}

/** Sends what is waiting. Resolves true when the queue is empty, false when a request failed. */
export function flushEvents(options: { keepalive?: boolean } = {}): Promise<boolean> {
  sending = sending.then(
    () => drain(options.keepalive === true).catch(() => false),
    () => false,
  )
  return sending
}

function schedule(): void {
  window.clearTimeout(timer)
  const wait =
    failures === 0
      ? FLUSH_EVERY_MS
      : Math.min(BACKOFF_MAX_MS, BACKOFF_FIRST_MS * 2 ** (failures - 1)) * (1 + Math.random() * 0.2)
  timer = window.setTimeout(async () => {
    await flushEvents()
    if (started) schedule()
  }, wait)
}

/** Starts sending for this session, and sends whatever an earlier page life left behind. */
export function startEventLog(id: string): void {
  if (started && sessionId === id) return
  stopEventLog()
  sessionId = id
  started = true
  halted = false
  failures = 0

  const onOnline = () => void flushEvents()
  const onHide = () => {
    if (document.visibilityState === 'hidden') void flushEvents({ keepalive: true })
  }
  const onPageHide = () => void flushEvents({ keepalive: true })
  window.addEventListener('online', onOnline)
  window.addEventListener('pagehide', onPageHide)
  document.addEventListener('visibilitychange', onHide)
  removeListeners = () => {
    window.removeEventListener('online', onOnline)
    window.removeEventListener('pagehide', onPageHide)
    document.removeEventListener('visibilitychange', onHide)
  }

  void flushEvents()
  schedule()
}

/** Stops the timer and listeners. Events logged afterwards are still kept on the device. */
export function stopEventLog(): void {
  window.clearTimeout(timer)
  removeListeners?.()
  removeListeners = null
  started = false
}

/** For tests. */
export function resetEventLog(): void {
  stopEventLog()
  sessionId = null
  halted = false
  failures = 0
  queued = 0
  writes = Promise.resolve()
  sending = Promise.resolve(true)
}
