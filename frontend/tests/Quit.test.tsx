import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import Quit from '../src/candidate/Quit'
import { QUIT_BODY, QUIT_LEAVE, QUIT_TITLE } from '../src/candidate/copy'
import { QUIT_PATH } from '../src/lib/routes'

describe('quit page', () => {
  afterEach(cleanup)

  it('says the window may close and what to do if it does not', () => {
    render(<Quit assign={vi.fn()} />)
    expect(screen.getByRole('heading', { name: QUIT_TITLE })).toBeTruthy()
    expect(screen.getByText(QUIT_BODY)).toBeTruthy()
  })

  it('asks again with a full page load of its own address when Leave is pressed', () => {
    const assign = vi.fn()
    render(<Quit assign={assign} />)
    fireEvent.click(screen.getByRole('button', { name: QUIT_LEAVE }))
    expect(assign).toHaveBeenCalledExactlyOnceWith(QUIT_PATH)
    expect(QUIT_PATH).toBe('/quit')
  })
})
