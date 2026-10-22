// The recording, kept on the device until the server confirms it. Each chunk is hashed, numbered and
// stored the moment the recorder hands it over; the uploader sends them afterwards, in order. The
// number (`seq`) counts through the whole session, across recorder runs and across reloads, so
// "nothing is missing" is one check on the server: every number from 0 to the total is there.

import { getStore } from './store'
import type { StoredChunk } from './store'

export interface ChunkCounts {
  /** Chunks made so far. */
  total: number
  pending: number
  done: number
  /** Chunks the server will never take (too large, or a different chunk already holds the number). */
  failed: number
  bytesPending: number
}

export async function sha256Hex(blob: Blob): Promise<string> {
  const buffer = await (typeof blob.arrayBuffer === 'function'
    ? blob.arrayBuffer()
    : new Response(blob).arrayBuffer())
  const digest = await crypto.subtle.digest('SHA-256', buffer)
  return [...new Uint8Array(digest)].map((byte) => byte.toString(16).padStart(2, '0')).join('')
}

const seqKey = (sessionId: string) => `chunks:${sessionId}`
const segmentKey = (sessionId: string) => `segments:${sessionId}`

/** Numbers and stores one chunk as pending. Returns what was stored. */
export async function addChunk(sessionId: string, segment: number, blob: Blob): Promise<StoredChunk> {
  const store = await getStore()
  const seq = await store.nextCounter(seqKey(sessionId))
  const chunk: StoredChunk = {
    sessionId,
    seq,
    segment,
    sha256: await sha256Hex(blob),
    size: blob.size,
    blob,
    status: 'pending',
  }
  await store.putChunk(chunk)
  return chunk
}

/** The number to put in `finish`: how many chunks this session has made, from this browser. */
export async function chunksTotal(sessionId: string): Promise<number> {
  return (await getStore()).peekCounter(seqKey(sessionId))
}

/** The number of the next recorder run: 0 for the first, then 1, 2 ... */
export async function nextSegment(sessionId: string): Promise<number> {
  return (await getStore()).nextCounter(segmentKey(sessionId))
}

export async function chunkCounts(sessionId: string): Promise<ChunkCounts> {
  const chunks = await (await getStore()).chunks(sessionId)
  const counts: ChunkCounts = { total: chunks.length, pending: 0, done: 0, failed: 0, bytesPending: 0 }
  for (const chunk of chunks) {
    if (chunk.status === 'pending') {
      counts.pending += 1
      counts.bytesPending += chunk.size
    } else if (chunk.status === 'done') counts.done += 1
    else counts.failed += 1
  }
  return counts
}
