import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { api, ApiError } from '../src/lib/api'
import { resetMock, setMockLatency } from '../src/lib/mock'
import { clearStaff, getStaff, saveStaff } from '../src/lib/staffSession'
import StaffApp from '../src/staff/StaffApp'

vi.mock('../src/lib/api', async (importOriginal) =>
  (await import('./helpers/mockedApi')).withMockedApi(await importOriginal()),
)

/** Shows the address, so a test can say where a redirect ended up. */
function Where() {
  const { pathname, search } = useLocation()
  return <p data-testid="where">{pathname + search}</p>
}

function renderAt(path: string) {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <Where />
      <Routes>
        <Route path="/" element={<p>entry page</p>} />
        <Route path="/login/*" element={<StaffApp section="login" />} />
        <Route path="/review/*" element={<StaffApp section="review" />} />
        <Route path="/admin/*" element={<StaffApp section="admin" />} />
      </Routes>
    </MemoryRouter>,
  )
}

const where = () => screen.getByTestId('where').textContent

const asReviewer = () =>
  saveStaff({ token: 'mock-reviewer:r@example.com', email: 'r@example.com', role: 'reviewer' })
const asAdmin = () =>
  saveStaff({ token: 'mock-admin:admin@example.com', email: 'admin@example.com', role: 'admin' })

function signInWith(email: string, password = 'secret') {
  fireEvent.change(screen.getByLabelText('Email'), { target: { value: email } })
  fireEvent.change(screen.getByLabelText('Password'), { target: { value: password } })
  fireEvent.click(screen.getByRole('button', { name: 'Sign in' }))
}

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
    it('sends a signed-out reviewer page to the reviewer sign-in, with a way back', async () => {
      renderAt('/review/audit')
      expect(await screen.findByRole('heading', { name: 'Reviewer sign in' })).toBeTruthy()
      expect(where()).toBe('/login/reviewer?next=%2Freview%2Faudit')
    })

    it('sends a signed-out admin page to the admin sign-in and returns there afterwards', async () => {
      renderAt('/admin/invites')
      expect(await screen.findByRole('heading', { name: 'Admin sign in' })).toBeTruthy()
      expect(where()).toBe('/login/admin?next=%2Fadmin%2Finvites')

      signInWith('admin@example.com')
      expect(await screen.findByLabelText(/How many new codes/)).toBeTruthy()
      expect(where()).toBe('/admin/invites')
    })

    it('keeps the old reviewer sign-in address working, and where the person was going', async () => {
      renderAt('/review/login?next=%2Freview%2Faudit')
      expect(await screen.findByRole('heading', { name: 'Reviewer sign in' })).toBeTruthy()
      expect(where()).toBe('/login/reviewer?next=%2Freview%2Faudit')
    })

    it('signs a reviewer in and lands on the queue', async () => {
      renderAt('/login/reviewer')
      await screen.findByRole('heading', { name: 'Reviewer sign in' })
      signInWith('r@example.com')

      expect(await screen.findByRole('heading', { name: 'Review queue' })).toBeTruthy()
      expect(getStaff()?.role).toBe('reviewer')
      expect(screen.getByText('r@example.com (reviewer)')).toBeTruthy()
    })

    it('lets an admin use the reviewer sign-in, which lands on the queue', async () => {
      renderAt('/login/reviewer')
      await screen.findByRole('heading', { name: 'Reviewer sign in' })
      signInWith('admin@example.com')

      expect(await screen.findByRole('heading', { name: 'Review queue' })).toBeTruthy()
      expect(getStaff()?.role).toBe('admin')
    })

    it('lands an admin on the sittings from the admin sign-in', async () => {
      renderAt('/login/admin')
      await screen.findByRole('heading', { name: 'Admin sign in' })
      signInWith('admin@example.com')

      expect(await screen.findByRole('heading', { name: 'Sittings' })).toBeTruthy()
    })

    it('tells a reviewer the admin sign-in is not for them and keeps nothing', async () => {
      renderAt('/login/admin')
      await screen.findByRole('heading', { name: 'Admin sign in' })
      signInWith('r@example.com')

      const alert = await screen.findByRole('alert')
      expect(alert.textContent).toMatch(/reviewer account/)
      expect(within(alert).getByRole('link', { name: 'Use the reviewer sign in' })).toBeTruthy()
      expect(getStaff()).toBeNull()
    })

    it('shows a plain message for a wrong password and stays signed out', async () => {
      renderAt('/login/reviewer')
      await screen.findByRole('heading', { name: 'Reviewer sign in' })
      signInWith('r@example.com', 'wrong')

      expect((await screen.findByRole('alert')).textContent).toBe(
        'The email or password is not right.',
      )
      expect(getStaff()).toBeNull()
    })

    it('says how long to wait after too many wrong attempts', async () => {
      vi.mocked(api).mockRejectedValueOnce(
        new ApiError(429, 'too_many_attempts', { code: 'too_many_attempts', retry_after_s: 600 }),
      )
      renderAt('/login/reviewer')
      await screen.findByRole('heading', { name: 'Reviewer sign in' })
      signInWith('r@example.com')

      expect((await screen.findByRole('alert')).textContent).toMatch(/wait about 10 minutes/)
    })

    it('links each sign-in to the other one and back to the entry page', async () => {
      renderAt('/login/reviewer')
      const toAdmin = await screen.findByRole('link', { name: /Admin sign in/ })
      expect(toAdmin.getAttribute('href')).toBe('/login/admin')
      expect(screen.getByRole('link', { name: 'All sign-ins' }).getAttribute('href')).toBe('/')

      cleanup()
      renderAt('/login/admin')
      const toReviewer = await screen.findByRole('link', { name: /Reviewer sign in/ })
      expect(toReviewer.getAttribute('href')).toBe('/login/reviewer')
    })

    it('sends someone already signed in straight to their pages', async () => {
      asReviewer()
      renderAt('/login/admin')
      expect(await screen.findByRole('heading', { name: 'Review queue' })).toBeTruthy()

      cleanup()
      clearStaff()
      asAdmin()
      renderAt('/login/admin')
      expect(await screen.findByRole('heading', { name: 'Sittings' })).toBeTruthy()
    })

    it('signs out and lands on the entry page', async () => {
      asReviewer()
      renderAt('/review')
      fireEvent.click(await screen.findByRole('button', { name: 'Sign out' }))
      expect(await screen.findByText('entry page')).toBeTruthy()
      expect(getStaff()).toBeNull()
    })

    it('returns an expired admin session to the admin sign-in, a reviewer to the reviewer one', async () => {
      saveStaff({ token: 'mock-expired:a@example.com', email: 'a@example.com', role: 'admin' })
      renderAt('/admin')
      expect(await screen.findByRole('heading', { name: 'Admin sign in' })).toBeTruthy()
      expect(getStaff()).toBeNull()

      cleanup()
      saveStaff({ token: 'mock-expired:r@example.com', email: 'r@example.com', role: 'reviewer' })
      renderAt('/review')
      expect(await screen.findByRole('heading', { name: 'Reviewer sign in' })).toBeTruthy()
    })
  })

  describe('moving around', () => {
    it('makes the title a link to the person’s own home', async () => {
      asReviewer()
      renderAt('/review/audit')
      const brand = await screen.findByRole('link', { name: 'Integrity review' })
      expect(brand.getAttribute('href')).toBe('/review')

      cleanup()
      clearStaff()
      asAdmin()
      renderAt('/admin/invites')
      expect(
        (await screen.findByRole('link', { name: 'Integrity review' })).getAttribute('href'),
      ).toBe('/admin')
    })

    it('shows where a deep page sits and how to get back', async () => {
      asReviewer()
      renderAt('/review/candidates/cand-007')
      const crumbs = await screen.findByRole('navigation', { name: 'Breadcrumb' })
      expect(within(crumbs).getByRole('link', { name: 'Review' }).getAttribute('href')).toBe(
        '/review',
      )
      expect(within(crumbs).getByText('Candidate cand-007').getAttribute('aria-current')).toBe(
        'page',
      )
    })

    it('shows no breadcrumb at the top of a section', async () => {
      asReviewer()
      renderAt('/review')
      await screen.findByRole('heading', { name: 'Review queue' })
      expect(screen.queryByRole('navigation', { name: 'Breadcrumb' })).toBeNull()
    })

    it('puts the admin section in the trail of the setup pages', async () => {
      asAdmin()
      renderAt('/admin/questions')
      const crumbs = await screen.findByRole('navigation', { name: 'Breadcrumb' })
      expect(within(crumbs).getByRole('link', { name: 'Admin' }).getAttribute('href')).toBe('/admin')
      expect(within(crumbs).getByText('Questions')).toBeTruthy()
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
