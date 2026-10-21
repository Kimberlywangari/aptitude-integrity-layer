// What the candidate's browser keeps on the device until the server has it: the action log and the
// video chunks. Both are written here first and sent afterwards, so a dropped connection, a reload
// or a closed tab loses nothing that was already recorded.
//
// IndexedDB does the keeping. When it is not available (a private window, site data blocked) the
// same API runs in memory instead: the test still works, but nothing survives a reload. `persistent`
// says which one this is.

import { openDB } from 'idb'
import type { DBSchema, IDBPDatabase } from 'idb'

export interface StoredEvent {
  sessionId: string
  /** The server's `client_seq`: counts up through the whole session and never repeats. */
  seq: number
  type: string
  payload?: Record<string, unknown>
  /** When it happened. `mono` (performance.now) is exact within one page life; after a reload it
   *  restarts, so `origin` (performance.timeOrigin) says whether it is still comparable and
   *  `epoch` (the wall clock) is what is left when it is not. */
  mono: number
  origin: number
  epoch: number
}

export type ChunkStatus = 'pending' | 'done' | 'failed'

export interface StoredChunk {
  sessionId: string
  /** Counts 0, 1, 2 ... through the whole session, across recorder runs. */
  seq: number
  /** Which recorder run made it. A run starts with its own container header. */
  segment: number
  sha256: string
  size: number
  /** The bytes, kept until the server confirms them; null afterwards (the row stays as a record). */
  blob: Blob | null
  status: ChunkStatus
}

export interface DeviceStore {
  readonly persistent: boolean
  putEvent(event: StoredEvent): Promise<void>
  /** The oldest events of a session, in `seq` order. */
  events(sessionId: string, limit: number): Promise<StoredEvent[]>
  deleteEvents(sessionId: string, seqs: number[]): Promise<void>
  putChunk(chunk: StoredChunk): Promise<void>
  chunk(sessionId: string, seq: number): Promise<StoredChunk | undefined>
  chunks(sessionId: string): Promise<StoredChunk[]>
  /** The lowest `seq` still waiting to be uploaded. */
  nextPendingChunk(sessionId: string): Promise<StoredChunk | undefined>
  /** A number that goes up by one each call and survives a reload: the next `client_seq`, chunk
   *  `seq` or segment of a session. The first call returns 0. */
  nextCounter(key: string): Promise<number>
  /** What `nextCounter` would give next, without using it. */
  peekCounter(key: string): Promise<number>
  /** Sessions that still have chunks to upload from this browser. */
  sessionsWithPendingChunks(): Promise<string[]>
}

// ------------------------------------------------------------------------------------- memory

// The counters are the one thing kept outside memory, in sessionStorage (the app already needs it to
// remember the session). If a reload wiped them, new events and chunks would reuse old numbers and
// the server would throw them away as repeats.
function counterStore() {
  const fallback = new Map<string, number>()
  const name = (key: string) => `integrity.counter.${key}`
  return {
    get(key: string): number {
      try {
        const raw = sessionStorage.getItem(name(key))
        if (raw !== null) return Number(raw) || 0
      } catch {
        // storage blocked: use memory
      }
      return fallback.get(key) ?? 0
    },
    set(key: string, value: number): void {
      fallback.set(key, value)
      try {
        sessionStorage.setItem(name(key), String(value))
      } catch {
        // storage blocked: memory only
      }
    },
  }
}

export function createMemoryStore(): DeviceStore {
  const events = new Map<string, StoredEvent>()
  const chunks = new Map<string, StoredChunk>()
  const counters = counterStore()
  const key = (sessionId: string, seq: number) => `${sessionId}:${seq}`
  const forSession = <T extends { sessionId: string; seq: number }>(map: Map<string, T>, id: string) =>
    [...map.values()].filter((row) => row.sessionId === id).sort((a, b) => a.seq - b.seq)

  return {
    persistent: false,
    async putEvent(event) {
      events.set(key(event.sessionId, event.seq), event)
    },
    async events(sessionId, limit) {
      return forSession(events, sessionId).slice(0, limit)
    },
    async deleteEvents(sessionId, seqs) {
      seqs.forEach((seq) => events.delete(key(sessionId, seq)))
    },
    async putChunk(chunk) {
      chunks.set(key(chunk.sessionId, chunk.seq), chunk)
    },
    async chunk(sessionId, seq) {
      return chunks.get(key(sessionId, seq))
    },
    async chunks(sessionId) {
      return forSession(chunks, sessionId)
    },
    async nextPendingChunk(sessionId) {
      return forSession(chunks, sessionId).find((chunk) => chunk.status === 'pending')
    },
    async nextCounter(name) {
      const value = counters.get(name)
      counters.set(name, value + 1)
      return value
    },
    async peekCounter(name) {
      return counters.get(name)
    },
    async sessionsWithPendingChunks() {
      return [...new Set([...chunks.values()].filter((c) => c.status === 'pending').map((c) => c.sessionId))]
    },
  }
}

// ----------------------------------------------------------------------------------- IndexedDB

interface Schema extends DBSchema {
  events: { key: [string, number]; value: StoredEvent }
  chunks: {
    key: [string, number]
    value: StoredChunk
    indexes: { byStatus: [string, string, number]; byState: string }
  }
  meta: { key: string; value: { key: string; value: number } }
}

type Db = IDBPDatabase<Schema>

const DB_NAME = 'integrity-device'
const DB_VERSION = 1

function createIndexedDbStore(db: Db): DeviceStore {
  const wholeSession = (sessionId: string) => IDBKeyRange.bound([sessionId, 0], [sessionId, Infinity])

  return {
    persistent: true,
    async putEvent(event) {
      await db.put('events', event)
    },
    async events(sessionId, limit) {
      return db.getAll('events', wholeSession(sessionId), limit)
    },
    async deleteEvents(sessionId, seqs) {
      const tx = db.transaction('events', 'readwrite')
      await Promise.all([...seqs.map((seq) => tx.store.delete([sessionId, seq])), tx.done])
    },
    async putChunk(chunk) {
      await db.put('chunks', chunk)
    },
    async chunk(sessionId, seq) {
      return db.get('chunks', [sessionId, seq])
    },
    async chunks(sessionId) {
      return db.getAll('chunks', wholeSession(sessionId))
    },
    async nextPendingChunk(sessionId) {
      const range = IDBKeyRange.bound([sessionId, 'pending', 0], [sessionId, 'pending', Infinity])
      return (await db.getAllFromIndex('chunks', 'byStatus', range, 1))[0]
    },
    async nextCounter(name) {
      // read and write in one transaction, so two callers can never be given the same number
      const tx = db.transaction('meta', 'readwrite')
      const row = await tx.store.get(name)
      const value = row?.value ?? 0
      await Promise.all([tx.store.put({ key: name, value: value + 1 }), tx.done])
      return value
    },
    async peekCounter(name) {
      return (await db.get('meta', name))?.value ?? 0
    },
    async sessionsWithPendingChunks() {
      const pending = await db.getAllFromIndex('chunks', 'byState', 'pending')
      return [...new Set(pending.map((chunk) => chunk.sessionId))]
    },
  }
}

// -------------------------------------------------------------------------------- the one store

let current: Promise<DeviceStore> | null = null

async function open(): Promise<DeviceStore> {
  try {
    if (typeof indexedDB === 'undefined') return createMemoryStore()
    const db = await openDB<Schema>(DB_NAME, DB_VERSION, {
      upgrade(upgrading) {
        upgrading.createObjectStore('events', { keyPath: ['sessionId', 'seq'] })
        const chunks = upgrading.createObjectStore('chunks', { keyPath: ['sessionId', 'seq'] })
        chunks.createIndex('byStatus', ['sessionId', 'status', 'seq'])
        chunks.createIndex('byState', 'status')
        upgrading.createObjectStore('meta', { keyPath: 'key' })
      },
    })
    return createIndexedDbStore(db)
  } catch {
    return createMemoryStore()
  }
}

/** The store for this page. Opened once; every caller gets the same one. */
export function getStore(): Promise<DeviceStore> {
  current ??= open()
  return current
}

/** For tests: use this store (or, with null, open the real one afresh next time). */
export function setStore(store: DeviceStore | null): void {
  current = store ? Promise.resolve(store) : null
}
