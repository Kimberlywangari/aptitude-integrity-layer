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
const rail = (w: VueWrapper, name: string) =>
  w.findAll('.rail-nav a').find((a) => a.text().replace(/\d+$/, '').trim() === name)
const tab = (w: VueWrapper, name: string) =>
  w.findAll('.tabs a').find((a) => a.text().trim() === name)
const filterButton = (w: VueWrapper, name: string) =>
  w.findAll('.filters button').find((b) => b.text().trim() === name)!
const queueIds = (w: VueWrapper) => w.findAll('a.q-item strong').map((s) => s.text())

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

    it('lands an admin on the sitting setup from the admin sign-in', async () => {
      const { w } = await renderAt('/login/admin')
      await untilHeading(w, 'Admin sign in')
      await signInWith(w, 'admin@example.com')
      await untilHeading(w, 'Admin')
      expect(tab(w, 'Sitting setup')!.attributes('aria-current')).toBe('page')
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
      await untilHeading(second.w, 'Admin')
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

    it('lists the pages in the rail, and the admin pages only for an admin', async () => {
      asReviewer()
      const first = await renderAt('/overview')
      await until(() => rail(first.w, 'Overview') !== undefined)
      expect(first.w.findAll('.rail-nav a').map((a) => a.text().replace(/\d+$/, '').trim())).toEqual([
        'Overview',
        'Review queue',
        'Audit log',
      ])

      clearStaff()
      asAdmin()
      const second = await renderAt('/overview')
      await until(() => rail(second.w, 'Admin') !== undefined)
      expect(rail(second.w, 'Admin')!.attributes('href')).toBe('/admin')
    })

    it('marks the part of the app the person is in, and keeps the queue lit on a candidate', async () => {
      asReviewer()
      const audit = await renderAt('/review/audit')
      await until(() => rail(audit.w, 'Audit log') !== undefined)
      expect(rail(audit.w, 'Audit log')!.attributes('aria-current')).toBe('page')
      expect(rail(audit.w, 'Review queue')!.attributes('aria-current')).toBeUndefined()

      const deep = await renderAt('/review/candidates/cand-007')
      await until(() => rail(deep.w, 'Review queue') !== undefined)
      expect(rail(deep.w, 'Review queue')!.attributes('aria-current')).toBe('page')
      expect(rail(deep.w, 'Audit log')!.attributes('aria-current')).toBeUndefined()
    })

    it('shows how many flagged candidates still wait, and updates it after a decision', async () => {
      asReviewer()
      const { w } = await renderAt('/review')
      await until(() => w.find('.rail-count').exists())
      expect(w.get('.rail-count').text()).toBe('6') // seven flagged, one already decided

      await w.get('a.q-item[href*="cand-009"]').trigger('click')
      await untilText(w, 'Candidate cand-009')
      await w.findAll('label.option').find((l) => l.text().includes('No concern'))!.get('input').setValue(true)
      await w.get('#reason').setValue('Screen froze, as the candidate said; timing fits.')
      await w.get('.check input').setValue(true)
      await w.findAll('form').at(-1)!.trigger('submit')
      await until(() => w.get('.rail-count').text() === '5')
    })

    it('puts the admin sections in tabs under one Admin heading', async () => {
      asAdmin()
      const { w } = await renderAt('/admin/questions')
      await untilHeading(w, 'Admin')
      expect(w.findAll('.tabs a').map((a) => a.text().trim())).toEqual([
        'Sitting setup',
        'Question bank',
        'Invitations',
      ])
      expect(tab(w, 'Question bank')!.attributes('aria-current')).toBe('page')
      expect(tab(w, 'Question bank')!.attributes('href')).toBe('/admin/questions')
      expect(rail(w, 'Admin')!.attributes('aria-current')).toBe('page')
    })
  })

  describe('overview', () => {
    beforeEach(asReviewer)

    it('shows where the sitting stands', async () => {
      const { w } = await renderAt('/overview')
      await untilHeading(w, 'Overview')
      await untilText(w, 'Sat this sitting')

      const tiles = w.findAll('.tile').map((t) => norm(t.text()))
      expect(tiles[0]).toContain('16')
      expect(tiles[1]).toContain('7')
      expect(tiles[2]).toMatch(/1 of 7/)
      expect(tiles[3]).toMatch(/13 of 14/)
    })

    it('says the sitting is still open, so flags are not final', async () => {
      const { w } = await renderAt('/overview')
      await untilText(w, /This sitting is still open/)
    })

    it('draws the flags by kind, most common first', async () => {
      const { w } = await renderAt('/overview')
      await until(() => w.find('.bars').exists())
      const rows = w.findAll('.bars li').map((li) => norm(li.text()))
      expect(rows[0]).toMatch(/^Run of correct answers after a gap\s*5$/)
      expect(rows.some((r) => /^Copy or cut attempt\s*3$/.test(r))).toBe(true)
      expect(rows.some((r) => r.startsWith('Logging problem (heartbeat gap)'))).toBe(true)
    })

    it('lists the system checks in words, not just colour', async () => {
      const { w } = await renderAt('/overview')
      await until(() => w.find('.checks').exists())
      const state = (label: string) =>
        w.findAll('.checks li').find((li) => li.text().startsWith(label))!.get('.pill').text()
      expect(state('Fact check on AI answers')).toBe('OK')
      expect(state('Camera and microphone gate')).toBe('Needs a look')
      expect(state('AI ranking')).toBe('Off')
    })

    it('lists who needs a person next and links to them', async () => {
      const { w } = await renderAt('/overview')
      await until(() => w.find('.next-row').exists())
      const rows = w.findAll('a.next-row')
      expect(rows.map((r) => r.get('strong').text())).toEqual(['cand-007', 'cand-012', 'cand-003'])
      expect(rows[0].attributes('href')).toBe('/review/candidates/cand-007')
      expect(rows[0].text()).toContain('High priority')
    })

    it('shows a sitting that has not run as empty', async () => {
      const { w } = await renderAt('/overview?sitting=2')
      await untilText(w, 'No one is flagged in this sitting yet.')
      expect(w.find('a.next-row').exists()).toBe(false)
    })
  })

  describe('review queue', () => {
    beforeEach(asReviewer)

    it('lists flagged candidates by rank with a priority band and a separate low lane', async () => {
      const { w } = await renderAt('/review')
      await untilHeading(w, 'Review queue')
      await until(() => queueIds(w).length > 0)

      expect(queueIds(w)).toEqual([
        'cand-007',
        'cand-012',
        'cand-003',
        'cand-015',
        'cand-009',
        'cand-018',
        'cand-004',
      ])
      const first = w.get('a.q-item')
      expect(first.attributes('href')).toBe('/review/candidates/cand-007')
      expect(first.text()).toContain('High')
      expect(first.text()).toContain('4 flags')

      // the candidate whose only flag is a gap in the record sits below a label of its own
      const lane = w.get('.lane-label')
      expect(lane.text()).toBe('Logging problems only (low priority)')
      expect(lane.element.nextElementSibling?.textContent).toContain('cand-004')
      expect(w.text()).toContain('Shortlisted')
      expect(w.text()).toContain('Decided') // cand-018 arrives with a decision
    })

    it('filters by priority band and by what is still pending', async () => {
      const { w } = await renderAt('/review')
      await until(() => queueIds(w).length === 7)

      await filterButton(w, 'High').trigger('click')
      expect(queueIds(w)).toEqual(['cand-007', 'cand-012', 'cand-003', 'cand-015'])
      expect(filterButton(w, 'High').attributes('aria-pressed')).toBe('true')

      await filterButton(w, 'Pending').trigger('click')
      expect(queueIds(w)).not.toContain('cand-018') // already decided
      expect(queueIds(w)).toHaveLength(6)

      await filterButton(w, 'Low').trigger('click')
      expect(queueIds(w)).toEqual(expect.arrayContaining(['cand-009', 'cand-004']))
      expect(queueIds(w)).not.toContain('cand-007')

      await filterButton(w, 'All').trigger('click')
      expect(queueIds(w)).toHaveLength(7)
    })

    it('shows an empty sitting plainly', async () => {
      const { w } = await renderAt('/review?sitting=2')
      await untilText(w, /No flagged candidates in this sitting yet/)
    })

    it('does not show the setup screens to a reviewer', async () => {
      const { w } = await renderAt('/review')
      await untilHeading(w, 'Review queue')
      expect(rail(w, 'Admin')).toBeUndefined()
    })

    it('opens a candidate beside the queue without losing it', async () => {
      const { w, router } = await renderAt('/review')
      await until(() => queueIds(w).length === 7)
      expect(w.text()).toContain('Choose a candidate')

      await w.get('a.q-item[href*="cand-012"]').trigger('click')
      await untilText(w, 'Candidate cand-012')
      expect(router.currentRoute.value.path).toBe('/review/candidates/cand-012')
      expect(queueIds(w)).toHaveLength(7)
      expect(w.get('a.q-item[href*="cand-012"]').attributes('aria-current')).toBe('page')
      expect(w.get('a.q-item[href*="cand-007"]').attributes('aria-current')).toBeUndefined()
    })
  })

  describe('candidate detail', () => {
    beforeEach(asReviewer)

    it('says plainly when a flag has no video and where the others land', async () => {
      const { w } = await renderAt('/review/candidates/cand-015')
      await untilText(w, 'Candidate cand-015')

      const rows = w.findAll('.flag-row')
      await rows[0].trigger('click') // F1 at 520 s: segment 0, 515 s
      await untilText(w, /part 1 at 8:35, starting 5 s before the moment/)

      await rows[2].trigger('click') // F3 at 930 s: inside the camera drop
      await untilText(w, /no video was recorded at this moment/)
    })

    it('puts the flags that have video on a timeline and jumps from them', async () => {
      const { w } = await renderAt('/review/candidates/cand-015')
      await untilText(w, 'Candidate cand-015')

      const marks = w.findAll('.timeline .mk')
      expect(marks).toHaveLength(2) // the third flag falls in a recording gap, so it has no marker
      expect(marks[0].attributes('aria-label')).toBe('Jump to F1 Copy or cut attempt at 8:40')

      await marks[1].trigger('click')
      await untilText(w, /F2 Focus lost: part 2 at 12:15, starting 5 s before the moment/)
    })

    it('labels AI text as advisory and context as context', async () => {
      const { w } = await renderAt('/review/candidates/cand-007')
      await untilText(w, 'Candidate cand-007')
      expect(w.text()).toMatch(/not a verdict and it decides nothing/)
      expect(w.text()).toContain('Checked against the stored log')
      expect(w.text()).toContain('Context only. Never a flag on its own.')
      expect(w.text()).toContain('What the AI makes of the flags')
    })

    it('makes no fact-check claim when the AI did not pass', async () => {
      const { w } = await renderAt('/review/candidates/cand-015')
      await untilText(w, 'Candidate cand-015')
      expect(w.text()).toContain('What the rules found')
      expect(w.text()).toContain('Rule-based summary')
      expect(w.text()).not.toContain('Checked against the stored log')
    })

    it('shows the priority band beside the rank', async () => {
      const { w } = await renderAt('/review/candidates/cand-007')
      await untilText(w, 'Candidate cand-007')
      expect(w.text()).toContain('High priority')
      expect(w.text()).toContain('Rank 1')
    })

    it('records a decision and shows it in the history', async () => {
      const { w } = await renderAt('/review/candidates/cand-009')
      await untilText(w, 'Candidate cand-009')

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

  describe('admin: sitting setup', () => {
    beforeEach(asAdmin)

    it('keeps the admin pages away from a reviewer', async () => {
      clearStaff()
      asReviewer()
      const { w } = await renderAt('/admin')
      await untilHeading(w, 'Review queue')
    })

    it('shows sittings and warns while placeholder questions are in the bank', async () => {
      const { w } = await renderAt('/admin')
      await untilHeading(w, 'Admin')
      await untilText(w, /60 placeholder questions are still in the question bank/)
      await untilText(w, 'Synthetic sitting 1')
    })

    it('shows where the setup stands, with a way to the next step', async () => {
      const { w } = await renderAt('/admin')
      await until(() => w.find('#setup-title').exists())
      const setup = w.get('section[aria-labelledby=setup-title]')

      expect(norm(setup.text())).toMatch(/Only placeholder questions so far \(60\)/)
      expect(link(setup as unknown as VueWrapper, 'Import the real questions')!.attributes('href')).toBe('/admin/questions')
      expect(norm(setup.text())).toContain('"Synthetic sitting 1" is open.')
      expect(norm(setup.text())).toContain('20 invitations for this sitting.')
      expect(norm(setup.text())).toMatch(/14 of 20 finished/)
    })

    it('starts each section at a few questions and adds them up', async () => {
      const { w } = await renderAt('/admin')
      await until(() => w.find('#per-numerical').exists())
      for (const section of ['logical', 'numerical', 'verbal']) {
        expect((w.get(`#per-${section}`).element as HTMLInputElement).value).toBe('4')
      }
      expect(norm(w.get('#paper-summary').text())).toContain('12 questions from 3 sections, 30 minutes.')
    })

    it('steps a section up and down and never past what the bank holds', async () => {
      const { w } = await renderAt('/admin')
      await until(() => w.find('#per-verbal').exists())
      const more = () => w.get('button[aria-label="More verbal questions"]')
      const fewer = () => w.get('button[aria-label="Fewer verbal questions"]')

      await more().trigger('click')
      expect((w.get('#per-verbal').element as HTMLInputElement).value).toBe('5')
      await fewer().trigger('click')
      await fewer().trigger('click')
      expect((w.get('#per-verbal').element as HTMLInputElement).value).toBe('3')

      await w.get('#per-verbal').setValue('99') // typed past the 20 in the bank
      await w.get('#per-verbal').trigger('change')
      expect((w.get('#per-verbal').element as HTMLInputElement).value).toBe('20')
      expect((more().element as HTMLButtonElement).disabled).toBe(true)

      await w.get('#per-verbal').setValue('0')
      await w.get('#per-verbal').trigger('change')
      expect((fewer().element as HTMLButtonElement).disabled).toBe(true)
    })

    it('cannot create a sitting with no questions, and says how many it has asked for', async () => {
      const { w } = await renderAt('/admin')
      await until(() => w.find('#per-verbal').exists())
      await w.get('#name').setValue('Empty')
      for (const section of ['logical', 'numerical', 'verbal']) {
        await w.get(`#per-${section}`).setValue('0')
        await w.get(`#per-${section}`).trigger('change')
      }
      expect(norm(w.get('#paper-summary').text())).toContain('0 questions from 0 sections')
      expect((button(w, 'Create sitting')!.element as HTMLButtonElement).disabled).toBe(true)
    })

    it('creates a sitting with the chosen questions from each section', async () => {
      const { w } = await renderAt('/admin')
      await until(() => w.find('#per-verbal').exists())
      await w.get('#name').setValue('Pilot 28 Oct')
      await w.get('#per-logical').setValue('0')
      await w.get('#per-logical').trigger('change')
      await w.get('#minutes').setValue('45')
      await w.get('#new-sitting form').trigger('submit')

      await untilText(w, 'Pilot 28 Oct')
      const row = norm(w.findAll('tbody tr').find((r) => r.text().includes('Pilot 28 Oct'))!.text())
      expect(row).toContain('45 min')
      expect(row).toContain('8 questions')
      expect(row).toContain('numerical 4, verbal 4')
    })

    it('says when a sitting with that name already exists', async () => {
      const { w } = await renderAt('/admin')
      await until(() => w.find('#name').exists())
      await w.get('#name').setValue('Synthetic sitting 1')
      await w.get('#new-sitting form').trigger('submit')

      await until(() => w.find('[role=alert]').exists())
      expect(norm(w.get('[role=alert]').text())).toBe('A sitting with that name already exists.')
    })

    it('asks before closing a sitting that has unfinished candidates', async () => {
      const { w } = await renderAt('/admin')
      await until(() => button(w, 'Close sitting') !== undefined)
      await button(w, 'Close sitting')!.trigger('click')
      await until(() => button(w, 'Close anyway (logged)') !== undefined)
      expect(w.text()).toMatch(/6 not finished/)
    })
  })

  describe('admin: invitations', () => {
    beforeEach(asAdmin)

    it('generates codes once and offers the download', async () => {
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
      const { w } = await renderAt('/admin/invites')
      await until(() => w.find('#count').exists())
      await w.get('#count').setValue('501')
      expect((button(w, 'Generate codes')!.element as HTMLButtonElement).disabled).toBe(true)
    })

    it('lists every candidate with where they are, in words', async () => {
      const { w } = await renderAt('/admin/invites')
      await until(() => w.findAll('#who ~ .table-wrap tbody tr, .table-wrap tbody tr').length >= 20)
      const status = (id: string) =>
        norm(w.findAll('tbody tr').find((r) => r.text().includes(id))!.text())
      expect(status('cand-001')).toContain('Finished')
      expect(status('cand-015')).toContain('Started')
      expect(status('cand-020')).toContain('Not opened')
    })

    it('shows new candidates in the list as not opened', async () => {
      const { w } = await renderAt('/admin/invites')
      await until(() => w.find('#count').exists())
      await w.get('#count').setValue('2')
      await w.get('form').trigger('submit')
      await untilText(w, '2 new codes')
      await until(() => w.findAll('tbody tr').some((r) => r.text().includes('cand-022')))
      expect(norm(w.findAll('tbody tr').find((r) => r.text().includes('cand-022') && r.text().includes('Not opened'))!.text())).toContain('cand-022')
    })

    it('makes a new link for a lost one, shown once', async () => {
      const { w } = await renderAt('/admin/invites')
      await until(() => w.find('button[aria-label="Resend link to cand-016"]').exists())
      await w.get('button[aria-label="Resend link to cand-016"]').trigger('click')

      await until(() => w.find('.tokenbox').exists())
      const box = w.get('.tokenbox')
      expect(box.text()).toContain('cand-016')
      expect(box.text()).toContain('The old code no longer works.')
      expect(box.get('code').text()).toMatch(/\/\?t=[0-9A-Z]{4}-[0-9A-Z]{4}$/)

      await button(box as unknown as VueWrapper, 'Hide')!.trigger('click')
      expect(w.find('.tokenbox').exists()).toBe(false)
    })
  })

  describe('admin: question bank', () => {
    beforeEach(asAdmin)

    it('shows what is in the bank and offers to remove the placeholders', async () => {
      const { w } = await renderAt('/admin/questions')
      await untilText(w, /60 questions: 0 from Cytonn, 60/)
      await button(w, 'Remove placeholder questions')!.trigger('click')
      expect(button(w, 'Yes, remove 60 placeholders')).toBeDefined()
      await button(w, 'Cancel')!.trigger('click')
      expect(button(w, 'Yes, remove 60 placeholders')).toBeUndefined()
    })

    it('lists the questions a page at a time, and says the correct share is pending', async () => {
      const { w } = await renderAt('/admin/questions')
      await until(() => w.findAll('#all-questions ~ * tbody tr, .panel tbody tr').length > 0)
      await untilText(w, 'Showing 60 of 60.')
      const rows = w.findAll('section[aria-labelledby=all-questions] tbody tr')
      expect(rows).toHaveLength(60)
      expect(norm(rows[0].text())).toContain('Pending')
      expect(norm(rows[0].text())).toContain('Placeholder')
    })

    it('filters the list by section', async () => {
      const { w } = await renderAt('/admin/questions')
      await untilText(w, 'Showing 60 of 60.')
      await w.get('#section-filter').setValue('verbal')
      await untilText(w, 'Showing 20 of 20.')
      const sections = w.findAll('section[aria-labelledby=all-questions] tbody tr td:nth-child(2)')
      expect(new Set(sections.map((td) => td.text()))).toEqual(new Set(['verbal']))
    })
  })
})
