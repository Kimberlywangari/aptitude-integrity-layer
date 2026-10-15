import { cleanup, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it } from 'vitest'
import App from '../src/App'

// The toggle is mounted once in the App shell, outside the routes, so every screen has it. This
// guards that arrangement: moving it inside a route would drop it from the other screens.
describe('light and dark toggle', () => {
  afterEach(() => {
    cleanup()
    window.history.pushState({}, '', '/')
  })

  it.each(['/', '/candidate', '/quit', '/not-seb', '/no/such/page'])('is on %s', (path) => {
    window.history.pushState({}, '', path)
    render(<App />)
    expect(screen.getByRole('button', { name: /^(dark|light) mode$/i })).toBeTruthy()
  })
})
