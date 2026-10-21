import 'fake-indexeddb/auto'
import { IDBFactory } from 'fake-indexeddb'
import { beforeEach, describe, expect, it } from 'vitest'
import { createMemoryStore, getStore, setStore } from '../src/lib/store'
import type { DeviceStore, StoredChunk, StoredEvent } from '../src/lib/store'

const event = (seq: number, sessionId = 's1'): StoredEvent => ({
  sessionId,
  seq,
  type: 'focus_lost',
  mono: 100 + seq,
  origin: 1,
  epoch: 1_000 + seq,
})

const chunk = (seq: number, status: StoredChunk['status'] = 'pending', sessionId = 's1'): StoredChunk => ({
  sessionId,
  seq,
  segment: 0,
  sha256: `hash-${seq}`,
  size: 100 + seq,
  blob: status === 'pending' ? new Blob(['x']) : null,
  status,
})

// The same behaviour, whether the device keeps things in IndexedDB or (when that is not available)
// in memory. A page must not be able to tell the difference.
const stores: [string, () => Promise<DeviceStore>][] = [
  ['IndexedDB', async () => (setStore(null), getStore())],
  ['memory', async () => createMemoryStore()],
]

describe.each(stores)('device store (%s)', (name, open) => {
  let store: DeviceStore

  beforeEach(async () => {
    globalThis.indexedDB = new IDBFactory() // a clean database for every test
    sessionStorage.clear()
    store = await open()
  })

  it('says whether it can survive a reload', () => {
    expect(store.persistent).toBe(name === 'IndexedDB')
  })

  it('returns the oldest events of a session first, up to the limit', async () => {
    for (const seq of [2, 0, 1, 3]) await store.putEvent(event(seq))
    await store.putEvent(event(0, 'other'))

    expect((await store.events('s1', 10)).map((e) => e.seq)).toEqual([0, 1, 2, 3])
    expect((await store.events('s1', 2)).map((e) => e.seq)).toEqual([0, 1])
    expect(await store.events('nobody', 10)).toEqual([])
  })

  it('deletes only the events named, in that session', async () => {
    for (const seq of [0, 1, 2]) await store.putEvent(event(seq))
    await store.putEvent(event(1, 'other'))

    await store.deleteEvents('s1', [0, 2])

    expect((await store.events('s1', 10)).map((e) => e.seq)).toEqual([1])
    expect(await store.events('other', 10)).toHaveLength(1)
  })

  it('counts up from zero, one number at a time, per name', async () => {
    expect(await store.peekCounter('events:s1')).toBe(0)
    const taken = await Promise.all([1, 2, 3].map(() => store.nextCounter('events:s1')))
    expect([...taken].sort()).toEqual([0, 1, 2]) // never the same number twice
    expect(await store.peekCounter('events:s1')).toBe(3)
    expect(await store.nextCounter('events:s2')).toBe(0)
  })

  it('finds the lowest chunk still waiting, and forgets the ones that are done', async () => {
    await store.putChunk(chunk(0, 'done'))
    await store.putChunk(chunk(2))
    await store.putChunk(chunk(1))
    await store.putChunk(chunk(0, 'pending', 'other'))

    expect((await store.nextPendingChunk('s1'))?.seq).toBe(1)
    await store.putChunk(chunk(1, 'done'))
    expect((await store.nextPendingChunk('s1'))?.seq).toBe(2)
    await store.putChunk(chunk(2, 'failed'))
    expect(await store.nextPendingChunk('s1')).toBeUndefined()
  })

  it('lists a session’s chunks in order', async () => {
    for (const seq of [2, 0, 1]) await store.putChunk(chunk(seq, 'done'))
    expect((await store.chunks('s1')).map((c) => c.seq)).toEqual([0, 1, 2])
    expect((await store.chunk('s1', 1))?.sha256).toBe('hash-1')
    expect(await store.chunk('s1', 9)).toBeUndefined()
  })

  it('knows which sessions still have chunks to send from this browser', async () => {
    await store.putChunk(chunk(0, 'done'))
    await store.putChunk(chunk(0, 'pending', 'other'))
    expect(await store.sessionsWithPendingChunks()).toEqual(['other'])
  })
})

describe('IndexedDB only', () => {
  it('keeps events, chunks and counters when the page is opened again', async () => {
    globalThis.indexedDB = new IDBFactory()
    setStore(null)
    const first = await getStore()
    await first.putEvent(event(0))
    await first.putChunk(chunk(0))
    await first.nextCounter('chunks:s1')

    setStore(null) // a reload: nothing is held in memory any more
    const second = await getStore()

    expect((await second.events('s1', 10)).map((e) => e.seq)).toEqual([0])
    expect((await second.nextPendingChunk('s1'))?.seq).toBe(0)
    expect(await second.peekCounter('chunks:s1')).toBe(1)
  })

  it('falls back to memory, quietly, when IndexedDB cannot be opened', async () => {
    const real = globalThis.indexedDB
    // a browser that refuses (private mode, blocked site data)
    globalThis.indexedDB = {
      open: () => {
        throw new DOMException('blocked', 'SecurityError')
      },
    } as unknown as IDBFactory
    setStore(null)

    const store = await getStore()
    globalThis.indexedDB = real

    expect(store.persistent).toBe(false)
    await store.putEvent(event(0))
    expect(await store.events('s1', 10)).toHaveLength(1)
  })
})

describe('memory store counters', () => {
  it('survive a reload of the page, so the server never sees a number twice', async () => {
    sessionStorage.clear()
    const before = createMemoryStore()
    await before.nextCounter('events:s1')
    await before.nextCounter('events:s1')

    const afterReload = createMemoryStore() // the data is gone; the numbering is not
    expect(await afterReload.nextCounter('events:s1')).toBe(2)
  })
})
