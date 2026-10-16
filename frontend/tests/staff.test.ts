import { flushPromises } from '@vue/test-utils'
import type { VueWrapper } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { api, ApiError } from '../src/lib/api'
import { resetMock, setMockLatency } from '../src/lib/mock'
import { clearStaff, getStaff, saveStaff } from '../src/lib/staffSession'
import { clearQueryClient } from '../src/staff/queryClient'
import { renderApp, until } from './helpers/render'

vi.mock('../src/lib/api', async (importOriginal) =>
  (await import('./helpers/mockedApi')).withMockedApi(await importOriginal()),
)

async function renderAt(path: string) {
  const { wrapper, router } = await renderApp(path)
  await flushPromises()
  return { w: wrapper, router }
}

const norm = (text: string) => text.replace(/\s+/g, ' ').trim()
const heading = (w: VueWrapper) => (w.find('h1').exists() ? w.get('h1').text() : '')
const untilHeading = (w: VueWrapper, name: string) => until(() => heading(w) === name)
const untilText = (w: VueWrapper, re: RegExp | string) =>
  until(() => (typeof re === 'string' ? norm(w.text()).includes(re) : re.test(norm(w.text()))))
const button = (w: VueWrapper, name: string) => w.findAll('button').find((b) => b.text().trim() === name)
const link = (w: VueWrapper, name: string | RegExp) =>
  w.findAll('a').find((a) => (typeof name === 'string' ? a.text().trim() === name : name.test(a.text())))

const asReviewer = () =>
  saveStaff({ token: 'mock-reviewer:r@example.com', email: 'r@example.com', role: 'reviewer' })
const asAdmin = () =>
  saveStaff({ token: 'mock-admin:admin@example.com', email: 'admin@example.com', role: 'admin' })

async function signInWith(w: VueWrapper, email: string, password = 'secret') {
  await w.get('#email').setValue(email)
  await w.get('#password').setValue(password)
  await w.get('form').trigger('submit')
}

describe('staff app', () => {
  beforeEach(() => {
    setMockLatency(0)
    resetMock()
    clearStaff()
    clearQueryClient()
  })

  afterEach(() => {
    clearStaff()
    clearQueryClient()
    document.body.innerHTML = ''
  })

  describe('signing in', () => {
    it('sends a signed-out reviewer page to the reviewer sign-in, with a way back', async () => {
      const { w, router } = await renderAt('/review/audit')
      await untilHeading(w, 'Reviewer sign in')
      expect(router.currentRoute.value.path).toBe('/login/reviewer')
      expect(router.currentRoute.value.query.next).toBe('/review/audit')
    })

    it('sends a signed-out admin page to the admin sign-in and returns there afterwards', async () => {
      const { w, router } = await renderAt('/admin/invites')
      await untilHeading(w, 'Admin sign in')
      expect(router.currentRoute.value.path).toBe('/login/admin')
      expect(router.currentRoute.value.query.next).toBe('/admin/invites')

      await signInWith(w, 'admin@example.com')
      await until(() => w.find('#count').exists())
      expect(router.currentRoute.value.path).toBe('/admin/invites')
    })

    it('keeps the old reviewer sign-in address working, and where the person was going', async () => {
      const { w, router } = await renderAt('/review/login?next=%2Freview%2Faudit')
      await untilHeading(w, 'Reviewer sign in')
      expect(router.currentRoute.value.path).toBe('/login/reviewer')
      expect(router.currentRoute.value.query.next).toBe('/review/audit')
    })

    it('only returns to staff pages, never an address someone else supplied', async () => {
      const { w, router } = await renderAt('/login/reviewer?next=https%3A%2F%2Fevil.example.com')
      await untilHeading(w, 'Reviewer sign in')
      await signInWith(w, 'r@example.com')
      await untilHeading(w, 'Review queue')
      expect(router.currentRoute.value.path).toBe('/review')
    })

    it('signs a reviewer in and lands on the queue', async () => {
      const { w } = await renderAt('/login/reviewer')
      await untilHeading(w, 'Reviewer sign in')
      await signInWith(w, 'r@example.com')

      await untilHeading(w, 'Review queue')
      expect(getStaff()?.role).toBe('reviewer')
      expect(w.text()).toContain('r@example.com (reviewer)')
    })

    it('lets an admin use the reviewer sign-in, which lands on the queue', async () => {
      const { w } = await renderAt('/login/reviewer')
      await untilHeading(w, 'Reviewer sign in')
      await signInWith(w, 'admin@example.com')

      await untilHeading(w, 'Review queue')
      expect(getStaff()?.role).toBe('admin')
    })

    it('lands an admin on the sittings from the admin sign-in', async () => {
      const { w } = await renderAt('/login/admin')
      await untilHeading(w, 'Admin sign in')
      await signInWith(w, 'admin@example.com')
      await untilHeading(w, 'Sittings')
    })

    it('tells a reviewer the admin sign-in is not for them and keeps nothing', async () => {
      const { w } = await renderAt('/login/admin')
      await untilHeading(w, 'Admin sign in')
      await signInWith(w, 'r@example.com')

      await until(() => w.find('[role=alert]').exists())
      const alert = w.get('[role=alert]')
      expect(alert.text()).toMatch(/reviewer account/)
      expect(alert.find('a').text()).toBe('Use the reviewer sign in')
      expect(getStaff()).toBeNull()
    })

    it('shows a plain message for a wrong password and stays signed out', async () => {
      const { w } = await renderAt('/login/reviewer')
      await untilHeading(w, 'Reviewer sign in')
      await signInWith(w, 'r@example.com', 'wrong')

      await until(() => w.find('[role=alert]').exists())
      expect(norm(w.get('[role=alert]').text())).toBe('The email or password is not right.')
      expect(getStaff()).toBeNull()
    })

    it.each([
      [45, /wait about 1 minute and/],
      [60, /wait about 1 minute and/],
      [61, /wait about 2 minutes and/],
    ])('says how long to wait after too many wrong attempts (%i s)', async (seconds, message) => {
      vi.mocked(api).mockRejectedValueOnce(
        new ApiError(429, 'too_many_attempts', { code: 'too_many_attempts', retry_after_s: seconds }),
      )
      const { w } = await renderAt('/login/reviewer')
      await untilHeading(w, 'Reviewer sign in')
      await signInWith(w, 'r@example.com')

      await until(() => w.find('[role=alert]').exists())
      expect(w.get('[role=alert]').text()).toMatch(message)
    })

    it('links each sign-in to the other one and back to the entry page', async () => {
      const first = await renderAt('/login/reviewer')
      await untilHeading(first.w, 'Reviewer sign in')
      expect(link(first.w, /Admin sign in/)!.attributes('href')).toBe('/login/admin')
      expect(link(first.w, 'All sign-ins')!.attributes('href')).toBe('/')

      const second = await renderAt('/login/admin')
      await untilHeading(second.w, 'Admin sign in')
      expect(link(second.w, /Reviewer sign in/)!.attributes('href')).toBe('/login/reviewer')
    })

    it('sends someone already signed in straight to their pages', async () => {
      asReviewer()
      const first = await renderAt('/login/admin')
      await untilHeading(first.w, 'Review queue')

      clearStaff()
      asAdmin()
      const second = await renderAt('/login/admin')
      await untilHeading(second.w, 'Sittings')
    })

    it('signs out and lands on the entry page', async () => {
      asReviewer()
      const { w, router } = await renderAt('/review')
      await until(() => button(w, 'Sign out') !== undefined)
      await button(w, 'Sign out')!.trigger('click')
      await until(() => router.currentRoute.value.path === '/')
      expect(w.text()).toContain('Choose who you are to continue')
      expect(getStaff()).toBeNull()
    })

    it('returns an expired admin session to the admin sign-in, a reviewer to the reviewer one', async () => {
      saveStaff({ token: 'mock-expired:a@example.com', email: 'a@example.com', role: 'admin' })
      const first = await renderAt('/admin')
      await untilHeading(first.w, 'Admin sign in')
      expect(getStaff()).toBeNull()

      clearQueryClient()
      saveStaff({ token: 'mock-expired:r@example.com', email: 'r@example.com', role: 'reviewer' })
      const second = await renderAt('/review')
      await untilHeading(second.w, 'Reviewer sign in')
    })
  })

  describe('moving around', () => {
    it('makes the title a link to the person’s own home', async () => {
      asReviewer()
      const first = await renderAt('/review/audit')
      await until(() => first.w.find('.staff-brand').exists())
      expect(first.w.get('.staff-brand').attributes('href')).toBe('/review')

      clearStaff()
      asAdmin()
      const second = await renderAt('/admin/invites')
      await until(() => second.w.find('.staff-brand').exists())
      expect(second.w.get('.staff-brand').attributes('href')).toBe('/admin')
    })

    it('shows where a deep page sits and how to get back', async () => {
      asReviewer()
      const { w } = await renderAt('/review/candidates/cand-007')
      await until(() => w.find('nav[aria-label=Breadcrumb]').exists())
      const crumbs = w.get('nav[aria-label=Breadcrumb]')
      expect(crumbs.find('a').text()).toBe('Review')
      expect(crumbs.find('a').attributes('href')).toBe('/review')
      expect(crumbs.get('[aria-current=page]').text()).toBe('Candidate cand-007')
    })

    it('shows no breadcrumb at the top of a section', async () => {
      asReviewer()
      const { w } = await renderAt('/review')
      await untilHeading(w, 'Review queue')
      expect(w.find('nav[aria-label=Breadcrumb]').exists()).toBe(false)
    })

    it('puts the admin section in the trail of the setup pages', async () => {
      asAdmin()
      const { w } = await renderAt('/admin/questions')
      await until(() => w.find('nav[aria-label=Breadcrumb]').exists())
      const crumbs = w.get('nav[aria-label=Breadcrumb]')
      expect(crumbs.find('a').text()).toBe('Admin')
      expect(crumbs.find('a').attributes('href')).toBe('/admin')
      expect(crumbs.text()).toContain('Questions')
    })
  })

  describe('reviewer queue', () => {
    beforeEach(asReviewer)

    it('lists flagged candidates by rank with a separate low lane', async () => {
      const { w } = await renderAt('/review')
      await until(() => link(w, 'cand-007') !== undefined)
      expect(link(w, 'cand-007')!.attributes('href')).toBe('/review/candidates/cand-007')

      expect(w.text()).toContain('AI advisory 5/5')
      expect(w.text()).toContain('Rules only (AI check failed)')
      const lane = w.get('section[aria-labelledby=low-lane]')
      expect(lane.findAll('a').some((a) => a.text() === 'cand-004')).toBe(true)
      expect(w.text()).toContain('Shortlisted')
    })

    it('shows an empty sitting plainly', async () => {
      const { w } = await renderAt('/review?sitting=2')
      await untilText(w, /No flagged candidates in this sitting yet/)
    })

    it('does not show the setup screens to a reviewer', async () => {
      const { w } = await renderAt('/review')
      await untilHeading(w, 'Review queue')
      expect(link(w, 'Invites')).toBeUndefined()
    })
  })

  describe('candidate detail', () => {
    beforeEach(asReviewer)

    it('says plainly when a flag has no video and where the others land', async () => {
      const { w } = await renderAt('/review/candidates/cand-015')
      await untilHeading(w, 'Candidate cand-015')

      const jumps = w.findAll('button').filter((b) => b.text() === 'Jump to video')
      await jumps[0].trigger('click') // F1 at 520 s: segment 0, 515 s
      await untilText(w, /part 1 at 8:35, starting 5 s before the moment/)

      await jumps[2].trigger('click') // F3 at 930 s: inside the camera drop
      await untilText(w, /no video was recorded at this moment/)
    })

    it('labels AI text as advisory and context as context', async () => {
      const { w } = await renderAt('/review/candidates/cand-007')
      await untilHeading(w, 'Candidate cand-007')
      expect(w.text()).toMatch(/not a verdict and it decides nothing/)
      expect(w.text()).toContain('Context only. Never a flag on its own.')
    })

    it('records a decision and shows it in the history', async () => {
      const { w } = await renderAt('/review/candidates/cand-009')
      await untilHeading(w, 'Candidate cand-009')

      await w.findAll('label.option').find((l) => l.text().includes('No concern'))!.get('input').setValue(true)
      await w.get('#reason').setValue('Screen froze, as the candidate said; timing fits.')
      await w.get('.check input').setValue(true)
      await w.findAll('form').at(-1)!.trigger('submit')

      await untilText(w, 'Decision recorded.')
      await untilText(w, /No concern by r@example.com/)
    })

    it('tells the reviewer when a candidate is not in the queue', async () => {
      const { w } = await renderAt('/review/candidates/cand-999')
      await untilText(w, 'That candidate is not in the review queue.')
    })
  })

  describe('setup screens', () => {
    it('keeps them away from a reviewer', async () => {
      asReviewer()
      const { w } = await renderAt('/admin')
      await untilHeading(w, 'Review queue')
    })

    it('shows sittings and warns while placeholder questions are in the bank', async () => {
      asAdmin()
      const { w } = await renderAt('/admin')
      await untilHeading(w, 'Sittings')
      await untilText(w, /60 placeholder questions are still in the question bank/)
      await untilText(w, 'Synthetic sitting 1')
    })

    it('shows where the setup stands, with a way to the next step', async () => {
      asAdmin()
      const { w } = await renderAt('/admin')
      await until(() => w.find('#setup-title').exists())
      const setup = w.get('section[aria-labelledby=setup-title]')

      expect(norm(setup.text())).toMatch(/Only placeholder questions so far \(60\)/)
      expect(link(setup as unknown as VueWrapper, 'Import the real questions')!.attributes('href')).toBe('/admin/questions')
      expect(norm(setup.text())).toContain('"Synthetic sitting 1" is open.')
      expect(norm(setup.text())).toContain('20 invitations for this sitting.')
      expect(norm(setup.text())).toMatch(/14 of 20 finished/)
    })

    it('says when a sitting with that name already exists', async () => {
      asAdmin()
      const { w } = await renderAt('/admin')
      await until(() => w.find('#name').exists())
      await w.get('#name').setValue('Synthetic sitting 1')
      await w.get('#new-sitting form').trigger('submit')

      await until(() => w.find('[role=alert]').exists())
      expect(norm(w.get('[role=alert]').text())).toBe('A sitting with that name already exists.')
    })

    it('asks before closing a sitting that has unfinished candidates', async () => {
      asAdmin()
      const { w } = await renderAt('/admin')
      await until(() => button(w, 'Close sitting') !== undefined)
      await button(w, 'Close sitting')!.trigger('click')
      await until(() => button(w, 'Close anyway (logged)') !== undefined)
      expect(w.text()).toMatch(/6 not finished/)
    })

    it('generates codes once and offers the download', async () => {
      asAdmin()
      const { w } = await renderAt('/admin/invites')
      await until(() => w.find('#count').exists())
      await w.get('#count').setValue('3')
      await w.get('form').trigger('submit')

      await untilText(w, '3 new codes')
      expect(w.text()).toMatch(/shown once/)
      expect(button(w, 'Download CSV')).toBeDefined()
      expect(w.findAll('td.mono').filter((td) => /^[0-9A-Z]{4}-[0-9A-Z]{4}$/.test(td.text()))).toHaveLength(3)

      await button(w, 'Clear this list')!.trigger('click')
      expect(w.text()).not.toContain('3 new codes')
    })

    it('blocks an out-of-range invite count', async () => {
      asAdmin()
      const { w } = await renderAt('/admin/invites')
      await until(() => w.find('#count').exists())
      await w.get('#count').setValue('501')
      expect((button(w, 'Generate codes')!.element as HTMLButtonElement).disabled).toBe(true)
    })

    it('shows what is in the bank and offers to remove the placeholders', async () => {
      asAdmin()
      const { w } = await renderAt('/admin/questions')
      await untilText(w, /60 questions: 0 from Cytonn, 60/)
      await button(w, 'Remove placeholder questions')!.trigger('click')
      expect(button(w, 'Yes, remove 60 placeholders')).toBeDefined()
      await button(w, 'Cancel')!.trigger('click')
      expect(button(w, 'Yes, remove 60 placeholders')).toBeUndefined()
    })
  })
})
