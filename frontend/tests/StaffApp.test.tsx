import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { resetMock, setMockLatency } from '../src/lib/mock'
import { clearStaff, getStaff, saveStaff } from '../src/lib/staffSession'
import StaffApp from '../src/staff/StaffApp'

vi.mock('../src/lib/api', async (importOriginal) =>
  (await import('./helpers/mockedApi')).withMockedApi(await importOriginal()),
)

function renderAt(path: string) {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <Routes>
        <Route path="/review/*" element={<StaffApp section="review" />} />
        <Route path="/admin/*" element={<StaffApp section="admin" />} />
      </Routes>
    </MemoryRouter>,
  )
}

const asReviewer = () =>
  saveStaff({ token: 'mock-reviewer:r@example.com', email: 'r@example.com', role: 'reviewer' })
const asAdmin = () =>
  saveStaff({ token: 'mock-admin:admin@example.com', email: 'admin@example.com', role: 'admin' })

describe('staff app', () => {
  beforeEach(() => {
    setMockLatency(0)
    resetMock()
    clearStaff()
  })

  afterEach(() => {
    cleanup()
    clearStaff()
  })

  describe('signing in', () => {
    it('sends a signed-out visitor to the sign-in page', async () => {
      renderAt('/review')
      expect(await screen.findByRole('heading', { name: 'Sign in' })).toBeTruthy()
    })

    it('signs in and lands on the queue', async () => {
      renderAt('/review/login')
      fireEvent.change(await screen.findByLabelText('Email'), { target: { value: 'r@example.com' } })
      fireEvent.change(screen.getByLabelText('Password'), { target: { value: 'secret' } })
      fireEvent.click(screen.getByRole('button', { name: 'Sign in' }))

      expect(await screen.findByRole('heading', { name: 'Review queue' })).toBeTruthy()
      expect(getStaff()?.role).toBe('reviewer')
      expect(screen.getByText('r@example.com (reviewer)')).toBeTruthy()
    })

    it('shows a plain message for a wrong password and stays signed out', async () => {
      renderAt('/review/login')
      fireEvent.change(await screen.findByLabelText('Email'), { target: { value: 'r@example.com' } })
      fireEvent.change(screen.getByLabelText('Password'), { target: { value: 'wrong' } })
      fireEvent.click(screen.getByRole('button', { name: 'Sign in' }))

      expect((await screen.findByRole('alert')).textContent).toBe(
        'The email or password is not right.',
      )
      expect(getStaff()).toBeNull()
    })

    it('signs out and goes back to sign-in', async () => {
      asReviewer()
      renderAt('/review')
      fireEvent.click(await screen.findByRole('button', { name: 'Sign out' }))
      expect(await screen.findByRole('heading', { name: 'Sign in' })).toBeTruthy()
      expect(getStaff()).toBeNull()
    })
  })

  describe('reviewer queue', () => {
    beforeEach(asReviewer)

    it('lists flagged candidates by rank with a separate low lane', async () => {
      renderAt('/review')
      const link = await screen.findByRole('link', { name: 'cand-007' })
      expect(link.getAttribute('href')).toBe('/review/candidates/cand-007')

      expect(screen.getByText('AI advisory 5/5')).toBeTruthy()
      expect(screen.getByText('Rules only (AI check failed)')).toBeTruthy()
      const lane = screen.getByRole('region', { name: /Logging problems only/ })
      expect(within(lane).getByRole('link', { name: 'cand-004' })).toBeTruthy()
      expect(screen.getByText('Shortlisted')).toBeTruthy()
    })

    it('shows an empty sitting plainly', async () => {
      renderAt('/review?sitting=2')
      expect(await screen.findByText(/No flagged candidates in this sitting yet/)).toBeTruthy()
    })

    it('does not show the setup screens to a reviewer', async () => {
      renderAt('/review')
      await screen.findByRole('heading', { name: 'Review queue' })
      expect(screen.queryByRole('link', { name: 'Invites' })).toBeNull()
    })
  })

  describe('candidate detail', () => {
    beforeEach(asReviewer)

    it('says plainly when a flag has no video and where the others land', async () => {
      renderAt('/review/candidates/cand-015')
      await screen.findByRole('heading', { name: 'Candidate cand-015' })

      const jumps = screen.getAllByRole('button', { name: 'Jump to video' })
      fireEvent.click(jumps[0]) // F1 at 520 s: segment 0, 515 s
      await waitFor(() =>
        expect(screen.getByText(/part 1 at 8:35, starting 5 s before the moment/)).toBeTruthy(),
      )

      fireEvent.click(jumps[2]) // F3 at 930 s: inside the camera drop
      await waitFor(() =>
        expect(screen.getByText(/no video was recorded at this moment/)).toBeTruthy(),
      )
    })

    it('labels AI text as advisory and context as context', async () => {
      renderAt('/review/candidates/cand-007')
      await screen.findByRole('heading', { name: 'Candidate cand-007' })
      expect(screen.getByText(/not a verdict and it decides nothing/)).toBeTruthy()
      expect(screen.getAllByText('Context only. Never a flag on its own.').length).toBeGreaterThan(0)
    })

    it('records a decision and shows it in the history', async () => {
      renderAt('/review/candidates/cand-009')
      await screen.findByRole('heading', { name: 'Candidate cand-009' })

      fireEvent.click(screen.getByLabelText('No concern'))
      fireEvent.change(screen.getByLabelText(/Reason/), {
        target: { value: 'Screen froze, as the candidate said; timing fits.' },
      })
      fireEvent.click(screen.getByLabelText(/I have looked at the evidence/))
      fireEvent.click(screen.getByRole('button', { name: 'Record decision' }))

      expect(await screen.findByText('Decision recorded.')).toBeTruthy()
      expect(await screen.findByText(/No concern by r@example.com/)).toBeTruthy()
    })

    it('tells the reviewer when a candidate is not in the queue', async () => {
      renderAt('/review/candidates/cand-999')
      expect(await screen.findByText('That candidate is not in the review queue.')).toBeTruthy()
    })
  })

  describe('setup screens', () => {
    it('keeps them away from a reviewer', async () => {
      asReviewer()
      renderAt('/admin')
      expect(await screen.findByRole('heading', { name: 'Review queue' })).toBeTruthy()
    })

    it('shows sittings and warns while placeholder questions are in the bank', async () => {
      asAdmin()
      renderAt('/admin')
      expect(await screen.findByRole('heading', { name: 'Sittings' })).toBeTruthy()
      expect(await screen.findByText(/60 placeholder questions are still in the question bank/)).toBeTruthy()
      expect(await screen.findByText('Synthetic sitting 1')).toBeTruthy()
    })

    it('asks before closing a sitting that has unfinished candidates', async () => {
      asAdmin()
      renderAt('/admin')
      fireEvent.click(await screen.findByRole('button', { name: 'Close sitting' }))
      expect(await screen.findByRole('button', { name: 'Close anyway (logged)' })).toBeTruthy()
      expect(screen.getByText(/6 not finished/)).toBeTruthy()
    })

    it('generates codes once and offers the download', async () => {
      asAdmin()
      renderAt('/admin/invites')
      fireEvent.change(await screen.findByLabelText(/How many new codes/), { target: { value: '3' } })
      fireEvent.click(screen.getByRole('button', { name: 'Generate codes' }))

      expect(await screen.findByText('3 new codes')).toBeTruthy()
      expect(screen.getByText(/shown once/)).toBeTruthy()
      expect(screen.getByRole('button', { name: 'Download CSV' })).toBeTruthy()
      expect(screen.getAllByText(/^[0-9A-Z]{4}-[0-9A-Z]{4}$/)).toHaveLength(3)

      fireEvent.click(screen.getByRole('button', { name: 'Clear this list' }))
      expect(screen.queryByText('3 new codes')).toBeNull()
    })

    it('blocks an out-of-range invite count', async () => {
      asAdmin()
      renderAt('/admin/invites')
      fireEvent.change(await screen.findByLabelText(/How many new codes/), {
        target: { value: '501' },
      })
      expect((screen.getByRole('button', { name: 'Generate codes' }) as HTMLButtonElement).disabled).toBe(
        true,
      )
    })

    it('shows what is in the bank and offers to remove the placeholders', async () => {
      asAdmin()
      renderAt('/admin/questions')
      expect(await screen.findByText(/60 questions: 0 from Cytonn, 60/)).toBeTruthy()
      fireEvent.click(screen.getByRole('button', { name: 'Remove placeholder questions' }))
      expect(screen.getByRole('button', { name: 'Yes, remove 60 placeholders' })).toBeTruthy()
      fireEvent.click(screen.getByRole('button', { name: 'Cancel' }))
      expect(screen.queryByRole('button', { name: /Yes, remove/ })).toBeNull()
    })
  })
})
