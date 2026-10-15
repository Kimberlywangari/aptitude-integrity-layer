import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { applyTheme, currentTheme, storedTheme } from '../src/lib/theme'

function setSystemDark(dark: boolean) {
  Object.defineProperty(window, 'matchMedia', {
    configurable: true,
    writable: true,
    value: () => ({ matches: dark }),
  })
}

describe('theme', () => {
  beforeEach(() => {
    delete document.documentElement.dataset.theme
    window.localStorage.clear()
  })

  afterEach(() => {
    vi.restoreAllMocks()
    // @ts-expect-error jsdom has no matchMedia; remove the stub
    delete window.matchMedia
  })

  it('applies a theme to the page and remembers it', () => {
    applyTheme('dark')
    expect(document.documentElement.dataset.theme).toBe('dark')
    expect(storedTheme()).toBe('dark')
  })

  it('does not remember a theme that only follows the system', () => {
    applyTheme('dark', false)
    expect(document.documentElement.dataset.theme).toBe('dark')
    expect(storedTheme()).toBeNull()
  })

  it('prefers the applied theme, then the stored one, then the system one', () => {
    setSystemDark(true)
    expect(currentTheme()).toBe('dark')

    window.localStorage.setItem('theme', 'light')
    expect(currentTheme()).toBe('light')

    document.documentElement.dataset.theme = 'dark'
    expect(currentTheme()).toBe('dark')
  })

  it('ignores a stored value it does not recognise', () => {
    window.localStorage.setItem('theme', 'purple')
    expect(storedTheme()).toBeNull()
    expect(currentTheme()).toBe('light')
  })

  it('still applies the theme when storage is blocked', () => {
    vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => {
      throw new Error('blocked')
    })
    vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => {
      throw new Error('blocked')
    })
    expect(() => applyTheme('dark')).not.toThrow()
    expect(document.documentElement.dataset.theme).toBe('dark')
    expect(storedTheme()).toBeNull()
  })
})
