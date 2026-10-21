// A sign of life every 10 seconds while the test runs. The server turns a hole in the beats that a
// dropped connection or a reload does not explain into a "logging problem" for the reviewer, which
// is how a logger that was blocked or switched off shows up.
//
// The tick comes from a Web Worker, because a hidden tab's own timers are slowed right down by the
// browser (to once a minute after a few minutes). The worker is built from a string so there is no
// extra file to fetch in the middle of a test; if a worker cannot start, a plain timer does the job.

import { api, ApiError } from './api'
import type { HeartbeatResponse } from './api'
import { tracked } from './connection'

export const HEARTBEAT_MS = 10_000

const WORKER_SOURCE = `
let timer
onmessage = (message) => {
  clearInterval(timer)
  if (message.data && message.data.every) timer = setInterval(() => postMessage(1), message.data.every)
}
`

let stopCurrent: (() => void) | null = null

/** Starts the heartbeat. Returns the function that stops it; starting twice does nothing new. */
export function startHeartbeat(onBeat?: (beat: HeartbeatResponse) => void): () => void {
  if (stopCurrent) return stopCurrent

  let stopped = false
  let inFlight = false
  let timer: number | undefined
  let worker: Worker | null = null
  let workerUrl: string | null = null

  async function beat(): Promise<void> {
    if (stopped || inFlight) return // a slow reply must not pile beats up behind it
    inFlight = true
    try {
      // (not `onBeat?.(await ...)`: with no callback that never makes the request at all)
      const answer = await tracked(() => api<HeartbeatResponse>('/api/heartbeat', { method: 'POST' }))
      onBeat?.(answer)
    } catch (error) {
      // A token the server does not accept will never start working; anything else is a missed
      // beat, which is exactly what the server is watching for.
      if (error instanceof ApiError && error.status === 401) stop()
    } finally {
      inFlight = false
    }
  }

  function useTimer(): void {
    if (timer === undefined && !stopped) timer = window.setInterval(() => void beat(), HEARTBEAT_MS)
  }

  function stop(): void {
    stopped = true
    window.clearInterval(timer)
    worker?.terminate()
    if (workerUrl) URL.revokeObjectURL(workerUrl)
    stopCurrent = null
  }

  void beat() // the first one now, not in 10 s
  try {
    workerUrl = URL.createObjectURL(new Blob([WORKER_SOURCE], { type: 'text/javascript' }))
    worker = new Worker(workerUrl)
    worker.onmessage = () => void beat()
    worker.onerror = () => {
      worker?.terminate()
      worker = null
      useTimer()
    }
    worker.postMessage({ every: HEARTBEAT_MS })
  } catch {
    useTimer()
  }

  stopCurrent = stop
  return stop
}
