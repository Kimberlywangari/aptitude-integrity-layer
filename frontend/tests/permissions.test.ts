import { afterEach, describe, expect, it, vi } from 'vitest'
import { combine, queryPermission, watchPermission } from '../src/lib/permissions'

afterEach(() => {
  vi.unstubAllGlobals()
})

function fakePermissions(state: string) {
  const listeners = new Set<() => void>()
  const status = {
    state,
    addEventListener: (_: string, fn: () => void) => listeners.add(fn),
    removeEventListener: (_: string, fn: () => void) => listeners.delete(fn),
  }
  const query = vi.fn(async () => status)
  vi.stubGlobal('navigator', { permissions: { query } })
  return {
    query,
    change(next: string) {
      status.state = next
      listeners.forEach((fn) => fn())
    },
    count: () => listeners.size,
  }
}

describe('queryPermission()', () => {
  it('reports what the browser says for the camera and the microphone', async () => {
    const fake = fakePermissions('granted')
    expect(await queryPermission('camera')).toBe('granted')
    expect(await queryPermission('microphone')).toBe('granted')
    expect(fake.query).toHaveBeenCalledWith({ name: 'camera' })
    expect(fake.query).toHaveBeenCalledWith({ name: 'microphone' })
  })

  it('says unknown when the browser cannot answer', async () => {
    vi.stubGlobal('navigator', {})
    expect(await queryPermission('camera')).toBe('unknown')

    vi.stubGlobal('navigator', { permissions: { query: async () => Promise.reject(new TypeError('x')) } })
    expect(await queryPermission('camera')).toBe('unknown')
  })
})

describe('watchPermission()', () => {
  it('calls back when the candidate changes the setting, and stops when told to', async () => {
    const fake = fakePermissions('denied')
    const seen: string[] = []
    const stop = await watchPermission('camera', (state) => seen.push(state))

    fake.change('granted')
    expect(seen).toEqual(['granted'])

    stop()
    expect(fake.count()).toBe(0)
    fake.change('denied')
    expect(seen).toEqual(['granted'])
  })

  it('hands back a harmless function when the browser cannot answer', async () => {
    vi.stubGlobal('navigator', {})
    const stop = await watchPermission('camera', () => undefined)
    expect(() => stop()).not.toThrow()
  })
})

describe('combine()', () => {
  it('lets the worse answer win: blocked, then not asked, then allowed', () => {
    expect(combine('granted', 'granted')).toBe('granted')
    expect(combine('granted', 'prompt')).toBe('prompt')
    expect(combine('prompt', 'denied')).toBe('denied')
    expect(combine('denied', 'granted')).toBe('denied')
    expect(combine('granted', 'unknown')).toBe('unknown')
  })
})
