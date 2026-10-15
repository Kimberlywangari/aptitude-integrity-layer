import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it } from 'vitest'
import ThemeToggle from '../src/ThemeToggle'

describe('theme toggle', () => {
  beforeEach(() => {
    document.documentElement.dataset.theme = 'light'
    window.localStorage.clear()
  })

  afterEach(cleanup)

  it('offers the opposite of the current theme', () => {
    render(<ThemeToggle />)
    expect(screen.getByRole('button', { name: 'Dark mode' })).toBeTruthy()
  })

  it('switches the page and remembers the choice', () => {
    render(<ThemeToggle />)

    fireEvent.click(screen.getByRole('button', { name: 'Dark mode' }))
    expect(document.documentElement.dataset.theme).toBe('dark')
    expect(window.localStorage.getItem('theme')).toBe('dark')

    fireEvent.click(screen.getByRole('button', { name: 'Light mode' }))
    expect(document.documentElement.dataset.theme).toBe('light')
    expect(window.localStorage.getItem('theme')).toBe('light')
  })
})
