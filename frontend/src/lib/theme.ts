// Light and dark theme. The choice is kept in localStorage as a convenience only, so every read and
// write is guarded: storage can be blocked, and the page must still render. index.html applies the
// stored or system theme before the first paint; this file keeps it in step afterwards.

export type Theme = 'light' | 'dark'

const KEY = 'theme'

function isTheme(value: unknown): value is Theme {
  return value === 'light' || value === 'dark'
}

export function storedTheme(): Theme | null {
  try {
    const value = window.localStorage.getItem(KEY)
    return isTheme(value) ? value : null
  } catch {
    return null
  }
}

export function systemTheme(): Theme {
  if (typeof window.matchMedia !== 'function') return 'light'
  return window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light'
}

/** What the page is showing now: the applied theme, else the stored one, else the system's. */
export function currentTheme(): Theme {
  const applied = document.documentElement.dataset.theme
  return isTheme(applied) ? applied : (storedTheme() ?? systemTheme())
}

/** Show a theme. `remember` is false when it only follows the system, so a later change still follows. */
export function applyTheme(theme: Theme, remember = true): void {
  document.documentElement.dataset.theme = theme
  if (!remember) return
  try {
    window.localStorage.setItem(KEY, theme)
  } catch {
    // Not remembered, but it still applies for this visit.
  }
}
