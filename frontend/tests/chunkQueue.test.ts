import { beforeEach, describe, expect, it } from 'vitest'
import { addChunk, chunkCounts, chunksTotal, nextSegment, sha256Hex } from '../src/lib/chunkQueue'
import { createMemoryStore, setStore } from '../src/lib/store'

describe('chunk queue', () => {
  beforeEach(() => {
    sessionStorage.clear()
    setStore(createMemoryStore())
  })

  it('hashes the way the server does (SHA-256, lower-case hex)', async () => {
    // the standard test vector for "abc"
    expect(await sha256Hex(new Blob(['abc']))).toBe(
      'ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad',
    )
  })

  it('numbers chunks 0, 1, 2 ... through the whole session, across recorder runs', async () => {
    const a = await addChunk('s1', 0, new Blob(['aaaa']))
    const b = await addChunk('s1', 0, new Blob(['bb']))
    const c = await addChunk('s1', 1, new Blob(['c'])) // the camera dropped; a new run, same count

    expect([a.seq, b.seq, c.seq]).toEqual([0, 1, 2])
    expect([a.segment, b.segment, c.segment]).toEqual([0, 0, 1])
    expect(await chunksTotal('s1')).toBe(3)
    expect(await chunksTotal('s2')).toBe(0) // another session counts for itself
  })

  it('keeps the bytes and the hash until the server has the chunk', async () => {
    const stored = await addChunk('s1', 0, new Blob(['hello']))
    expect(stored.status).toBe('pending')
    expect(stored.size).toBe(5)
    expect(stored.blob).not.toBeNull()
    expect(stored.sha256).toBe(await sha256Hex(new Blob(['hello'])))
  })

  it('numbers recorder runs from zero', async () => {
    expect(await nextSegment('s1')).toBe(0)
    expect(await nextSegment('s1')).toBe(1)
    expect(await nextSegment('s2')).toBe(0)
  })

  it('counts what is waiting, done and given up on', async () => {
    const store = createMemoryStore()
    setStore(store)
    await addChunk('s1', 0, new Blob(['1234']))
    const second = await addChunk('s1', 0, new Blob(['12']))
    const third = await addChunk('s1', 0, new Blob(['1']))
    await store.putChunk({ ...second, blob: null, status: 'done' })
    await store.putChunk({ ...third, blob: null, status: 'failed' })

    expect(await chunkCounts('s1')).toEqual({
      total: 3,
      pending: 1,
      done: 1,
      failed: 1,
      bytesPending: 4,
    })
  })
})
