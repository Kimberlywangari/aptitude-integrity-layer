import { cleanup, render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, describe, expect, it } from 'vitest'
import NotSeb from '../src/candidate/NotSeb'
import { NOT_SEB_HELP, NOT_SEB_STEPS, NOT_SEB_TITLE } from '../src/candidate/copy'

describe('not in Safe Exam Browser', () => {
  afterEach(cleanup)

  function renderPage() {
    return render(
      <MemoryRouter>
        <NotSeb />
      </MemoryRouter>,
    )
  }

  it('says what is wrong, what to do in order, and who to ask', () => {
    renderPage()
    expect(screen.getByRole('heading', { name: NOT_SEB_TITLE })).toBeTruthy()
    const steps = screen.getAllByRole('listitem').map((item) => item.textContent)
    expect(steps).toEqual(NOT_SEB_STEPS)
    expect(screen.getByText(NOT_SEB_HELP)).toBeTruthy()
  })

  it('lets someone who is not taking the test back out to the sign-in options', () => {
    renderPage()
    const link = screen.getByRole('link', { name: /choose another sign-in/ })
    expect(link.getAttribute('href')).toBe('/')
  })
})
