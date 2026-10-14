import { cleanup, render, screen, within } from '@testing-library/react'
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom'
import { afterEach, describe, expect, it } from 'vitest'
import Entry from '../src/entry/Entry'

function Where() {
  const { pathname, search } = useLocation()
  return <p data-testid="where">{pathname + search}</p>
}

function renderEntry(path = '/') {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <Routes>
        <Route path="/" element={<Entry />} />
        <Route path="*" element={<Where />} />
      </Routes>
    </MemoryRouter>,
  )
}

describe('entry page', () => {
  afterEach(cleanup)

  it('offers one door for each kind of person', () => {
    renderEntry()
    const list = screen.getByRole('list')
    const hrefs = within(list)
      .getAllByRole('link')
      .map((link) => [link.textContent, link.getAttribute('href')])

    expect(hrefs).toEqual([
      [expect.stringMatching(/^Candidate/), '/candidate'],
      [expect.stringMatching(/^Reviewer/), '/login/reviewer'],
      [expect.stringMatching(/^Admin/), '/login/admin'],
    ])
  })

  it('forwards an old invitation link to code entry, keeping the code', () => {
    renderEntry('/?t=ABCD-EFGH')
    expect(screen.getByTestId('where').textContent).toBe('/candidate?t=ABCD-EFGH')
  })

  it('encodes the code it forwards', () => {
    renderEntry('/?t=a%20b%26c')
    expect(screen.getByTestId('where').textContent).toBe('/candidate?t=a%20b%26c')
  })

  it('does not forward when there is no code', () => {
    renderEntry('/?other=1')
    expect(screen.queryByTestId('where')).toBeNull()
    expect(screen.getByRole('heading', { name: 'Aptitude test' })).toBeTruthy()
  })
})
