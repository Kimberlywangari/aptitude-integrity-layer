import { vi } from 'vitest'

// A stand-in for src/lib/fullscreen.ts: jsdom has no full screen, and a test needs to say whether
// the page is in it. Use with
//   vi.mock('../src/lib/fullscreen', async () => (await import('./helpers/fakeFullscreen')).fullscreenModule)

export const fs = {
  active: false,
  supported: true,
  listeners: new Set<(full: boolean) => void>(),
}

export function setFullscreen(active: boolean): void {
  fs.active = active
  fs.listeners.forEach((listener) => listener(active))
}

export function resetFullscreen(): void {
  fs.active = false
  fs.supported = true
  fs.listeners.clear()
}

export const fullscreenModule = {
  fullscreenSupported: () => fs.supported,
  isFullscreen: () => fs.active,
  enterFullscreen: vi.fn(async () => {
    setFullscreen(true)
    return true
  }),
  leaveFullscreen: vi.fn(async () => setFullscreen(false)),
  onFullscreenChange: (callback: (full: boolean) => void) => {
    fs.listeners.add(callback)
    return () => fs.listeners.delete(callback)
  },
}
