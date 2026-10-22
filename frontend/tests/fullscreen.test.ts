import { afterEach, describe, expect, it, vi } from 'vitest'
import { fullscreenRequired, micCheckEnabled } from '../src/lib/features'
import {
  enterFullscreen,
  fullscreenSupported,
  isFullscreen,
  leaveFullscreen,
  onFullscreenChange,
} from '../src/lib/fullscreen'

// jsdom has no full screen, so these set up just the parts of `document` the module reads.
function setDocument(fields: Record<string, unknown>) {
  for (const [key, value] of Object.entries(fields)) {
    Object.defineProperty(document, key, { value, configurable: true, writable: true })
  }
}

afterEach(() => {
  for (const key of ['fullscreenEnabled', 'fullscreenElement', 'exitFullscreen']) {
    // eslint-disable-next-line @typescript-eslint/no-dynamic-delete
    delete (document as unknown as Record<string, unknown>)[key]
  }
  delete (document.documentElement as unknown as Record<string, unknown>).requestFullscreen
  vi.unstubAllEnvs()
})

describe('full screen helpers', () => {
  it('knows whether the browser allows it, and whether the page is in it', () => {
    setDocument({ fullscreenEnabled: true, fullscreenElement: null })
    expect(fullscreenSupported()).toBe(true)
    expect(isFullscreen()).toBe(false)

    setDocument({ fullscreenElement: document.documentElement })
    expect(isFullscreen()).toBe(true)

    setDocument({ fullscreenEnabled: false })
    expect(fullscreenSupported()).toBe(false)
  })

  it('asks for the whole page, and says whether the browser agreed', async () => {
    const request = vi.fn().mockResolvedValue(undefined)
    ;(document.documentElement as unknown as Record<string, unknown>).requestFullscreen = request
    expect(await enterFullscreen()).toBe(true)
    expect(request).toHaveBeenCalledWith({ navigationUI: 'hide' })

    request.mockRejectedValueOnce(new TypeError('not allowed'))
    expect(await enterFullscreen()).toBe(false)
  })

  it('leaves only when it is in full screen, and never throws', async () => {
    const exit = vi.fn().mockResolvedValue(undefined)
    setDocument({ fullscreenElement: null, exitFullscreen: exit })
    await leaveFullscreen()
    expect(exit).not.toHaveBeenCalled()

    setDocument({ fullscreenElement: document.documentElement })
    await leaveFullscreen()
    expect(exit).toHaveBeenCalledOnce()

    exit.mockRejectedValueOnce(new Error('refused'))
    await expect(leaveFullscreen()).resolves.toBeUndefined()
  })

  it('reports each change with the new state, until told to stop', () => {
    setDocument({ fullscreenElement: null })
    const seen: boolean[] = []
    const stop = onFullscreenChange((full) => seen.push(full))

    setDocument({ fullscreenElement: document.documentElement })
    document.dispatchEvent(new Event('fullscreenchange'))
    setDocument({ fullscreenElement: null })
    document.dispatchEvent(new Event('fullscreenchange'))
    expect(seen).toEqual([true, false])

    stop()
    document.dispatchEvent(new Event('fullscreenchange'))
    expect(seen).toEqual([true, false])
  })
})

describe('feature switches', () => {
  it('are all on unless a setting turns them off, which is how the pilot runs', () => {
    expect(micCheckEnabled()).toBe(true)
    expect(fullscreenRequired()).toBe(true)
  })

  it('can be turned off one at a time for testing', () => {
    vi.stubEnv('VITE_MIC_CHECK', 'off')
    expect(micCheckEnabled()).toBe(false)
    expect(fullscreenRequired()).toBe(true)

    vi.stubEnv('VITE_FULLSCREEN', 'off')
    expect(fullscreenRequired()).toBe(false)
  })

  it('treat any other value as on', () => {
    vi.stubEnv('VITE_FULLSCREEN', 'on')
    expect(fullscreenRequired()).toBe(true)
  })
})
