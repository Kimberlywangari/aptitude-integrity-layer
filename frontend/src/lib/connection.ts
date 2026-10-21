// Whether the page can reach the server, as the requests it makes find out. Two network failures in a
// row, or the browser saying it is offline, count as "lost"; the next request that gets any answer,
// or the browser saying it is back, counts as "restored". The action logger turns the changes into
// `connection_lost` and `connection_restored` events.
//
// Only a request that never got an answer counts as a failure. A 503 or a 409 is the server
// replying, so the connection is fine.

import { ApiError } from './api'

const FAILURES_BEFORE_LOST = 2

export interface ConnectionChange {
  lost: boolean
  /** performance.now() when it began: the first failure, or the moment of the change. */
  since: number
}

type Listener = (change: ConnectionChange) => void

let lost = false
let failures = 0
let firstFailureAt = 0
const listeners = new Set<Listener>()

function set(next: boolean, since: number): void {
  if (lost === next) return
  lost = next
  listeners.forEach((listener) => listener({ lost, since }))
}

export function isConnectionLost(): boolean {
  return lost
}

export function reportReply(): void {
  failures = 0
  set(false, performance.now())
}

export function reportNoReply(): void {
  if (failures === 0) firstFailureAt = performance.now()
  failures += 1
  if (failures >= FAILURES_BEFORE_LOST) set(true, firstFailureAt)
}

/** The browser's own `offline` / `online` signals. */
export function reportBrowserOffline(): void {
  failures = FAILURES_BEFORE_LOST
  set(true, performance.now())
}

export function reportBrowserOnline(): void {
  failures = 0
  set(false, performance.now())
}

/** Runs a request and keeps the connection state up to date from how it ended. */
export async function tracked<T>(request: () => Promise<T>): Promise<T> {
  try {
    const result = await request()
    reportReply()
    return result
  } catch (error) {
    if (error instanceof ApiError) reportReply()
    else reportNoReply()
    throw error
  }
}

export function onConnectionChange(listener: Listener): () => void {
  listeners.add(listener)
  return () => {
    listeners.delete(listener)
  }
}

/** For tests. */
export function resetConnection(): void {
  lost = false
  failures = 0
  firstFailureAt = 0
  listeners.clear()
}
