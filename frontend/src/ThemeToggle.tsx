import { useEffect, useState } from 'react'
import { applyTheme, currentTheme, storedTheme, systemTheme } from './lib/theme'
import type { Theme } from './lib/theme'

/** A small corner button. It follows the system setting until the person picks one, then keeps it. */
export default function ThemeToggle() {
  const [theme, setTheme] = useState<Theme>(currentTheme)

  // With no stored choice, follow the operating system if it changes while the page is open.
  useEffect(() => {
    if (typeof window.matchMedia !== 'function') return
    const query = window.matchMedia('(prefers-color-scheme: dark)')
    const onChange = () => {
      if (storedTheme()) return
      const next = systemTheme()
      applyTheme(next, false)
      setTheme(next)
    }
    query.addEventListener('change', onChange)
    return () => query.removeEventListener('change', onChange)
  }, [])

  function toggle() {
    const next: Theme = theme === 'dark' ? 'light' : 'dark'
    applyTheme(next)
    setTheme(next)
  }

  return (
    <button type="button" className="theme-toggle" onClick={toggle}>
      {theme === 'dark' ? 'Light mode' : 'Dark mode'}
    </button>
  )
}
