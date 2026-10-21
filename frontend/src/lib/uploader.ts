// Sends the recording to the server, one chunk at a time, lowest number first, for as long as the
// page is open. A chunk leaves the device only when the server says it has it ("stored", or
// "duplicate" for one it already held), so a dropped connection, a refusal or a closed tab costs
// nothing that cannot be sent again.
//
// A failure is waited out and the same chunk tried again: 1 s, 2 s, 4 s ... up to a minute, with a
// little randomness so that many candidates coming back online together do not all knock at once.
// Some answers will never change, and those stop the wait instead of repeating it forever:
//   401 the token is not ours (stop all uploading)      410 the upload window has closed (stop)
//   413 the chunk is too large                          409 another chunk already holds that number
// The last two give up on that one chunk and go on to the next; the server then shows it as missing.

import { api, ApiError } from './api'
import type { ChunkResponse } from './api'
import { chunkCounts } from './chunkQueue'
import type { ChunkCounts } from './chunkQueue'
import { tracked } from './connection'
import { getStore } from './store'

const BACKOFF_FIRST_MS = 1_000
const BACKOFF_MAX_MS = 60_000
const IDLE_WAIT_MS = 30_000
const CHECKSUM_TRIES = 5

export type UploadHalt = 'unauthorized' | 'closed' | null

export interface UploadStatus extends ChunkCounts {
  halted: UploadHalt
  /** True while a failed chunk is waiting to be tried again. */
  retrying: boolean
}

const EMPTY: UploadStatus = {
  total: 0,
  pending: 0,
  done: 0,
  failed: 0,
  bytesPending: 0,
  halted: null,
  retrying: false,
}

let sessionId: string | null = null
let running = false
let halted: UploadHalt = null
let retrying = false
let status: UploadStatus = EMPTY
let wake: (() => void) | null = null
const listeners = new Set<(status: UploadStatus) => void>()

async function publish(): Promise<void> {
  if (!sessionId) return
  status = { ...(await chunkCounts(sessionId)), halted, retrying }
  listeners.forEach((listener) => listener(status))
}

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => {
    const timer = window.setTimeout(done, ms)
    function done() {
      window.clearTimeout(timer)
      if (wake === done) wake = null
      resolve()
    }
    wake = done
  })
}

/** Cuts a wait short: new chunks to send, or the browser saying it is back online. */
export function wakeUploader(): void {
  wake?.()
}

function backoff(attempt: number): number {
  return Math.min(BACKOFF_MAX_MS, BACKOFF_FIRST_MS * 2 ** attempt) * (1 + Math.random() * 0.2)
}

async function loop(id: string): Promise<void> {
  const active = () => running && sessionId === id
  const store = await getStore()
  let attempt = 0
  let checksumFailures = 0
  await publish()

  while (active()) {
    const chunk = await store.nextPendingChunk(id)
    if (!chunk) {
      retrying = false
      await publish()
      await sleep(IDLE_WAIT_MS)
      continue
    }
    if (!chunk.blob) {
      // nothing left to send for this number (it should not happen); do not hold the line up
      await store.putChunk({ ...chunk, status: 'failed' })
      continue
    }

    try {
      await tracked(() =>
        api<ChunkResponse>(`/api/chunks/${id}/${chunk.seq}`, {
          method: 'PUT',
          bytes: chunk.blob as Blob,
          headers: {
            'X-Chunk-SHA256': chunk.sha256,
            'X-Chunk-Segment': String(chunk.segment),
          },
        }),
      )
      await store.putChunk({ ...chunk, blob: null, status: 'done' })
      attempt = 0
      checksumFailures = 0
      retrying = false
      await publish()
      continue
    } catch (error) {
      if (error instanceof ApiError) {
        if (error.status === 401) {
          halted = 'unauthorized'
          break
        }
        if (error.status === 410) {
          halted = 'closed'
          break
        }
        const neverWorks =
          error.status === 413 ||
          error.code === 'chunk_conflict' ||
          error.code === 'missing_checksum' ||
          error.code === 'bad_segment' ||
          (error.code === 'checksum_mismatch' && ++checksumFailures >= CHECKSUM_TRIES)
        if (neverWorks) {
          await store.putChunk({ ...chunk, blob: null, status: 'failed' })
          checksumFailures = 0
          await publish()
          continue
        }
      }
    }

    // the connection or the server is having a bad moment: wait, then the same chunk again
    retrying = true
    await publish()
    await sleep(backoff(attempt))
    attempt += 1
  }

  retrying = false
  await publish()
}

/** Starts sending this session's chunks. Safe to call again: it only wakes a running uploader. */
export function startUploader(id: string): void {
  if (running && sessionId === id && halted === null) {
    wakeUploader()
    return
  }
  stopUploader()
  sessionId = id
  running = true
  halted = null
  retrying = false
  window.addEventListener('online', wakeUploader)
  void loop(id)
}

export function stopUploader(): void {
  running = false
  sessionId = null
  window.removeEventListener('online', wakeUploader)
  wakeUploader()
  status = EMPTY
}

export function uploadStatus(): UploadStatus {
  return status
}

/** Calls back with the counts each time they change. Returns the function that stops listening. */
export function onUploadStatus(listener: (status: UploadStatus) => void): () => void {
  listeners.add(listener)
  return () => {
    listeners.delete(listener)
  }
}

/** Resolves true once at least `count` chunks are safely on the server, false after `timeoutMs`. */
export function waitForUploads(count: number, timeoutMs: number): Promise<boolean> {
  return new Promise((resolve) => {
    if (status.done >= count) return resolve(true)
    const timer = window.setTimeout(() => finish(false), timeoutMs)
    const stop = onUploadStatus((next) => {
      if (next.done >= count) finish(true)
      else if (next.halted) finish(false)
    })
    function finish(result: boolean) {
      window.clearTimeout(timer)
      stop()
      resolve(result)
    }
  })
}

/** For tests. */
export function resetUploader(): void {
  stopUploader()
  halted = null
  retrying = false
  listeners.clear()
}
