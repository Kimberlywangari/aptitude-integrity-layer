import { flushPromises } from '@vue/test-utils'
import type { VueWrapper } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { api, ApiError } from '../src/lib/api'
import { loadCytonnIntoMock, resetMock, setMockEmailed, setMockLatency, setMockMail, setMockResults } from './mock'
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
      expect(rows[0]).toMatch(/^Quick run of correct answers after a gap\s*5$/)
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
      expect(first.text()).toContain('3 flags')

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

    it('lists everyone in the sitting, including people the queue leaves out', async () => {
      const { w } = await renderAt('/review')
      await until(() => queueIds(w).length === 7)
      const everyoneButton = () =>
        w.findAll('.filters button').find((b) => b.text().startsWith('Everyone'))!

      await everyoneButton().trigger('click')
      await until(() => queueIds(w).length === 10)
      expect(queueIds(w)).toEqual([
        'cand-001',
        'cand-003',
        'cand-004',
        'cand-007',
        'cand-009',
        'cand-012',
        'cand-015',
        'cand-018',
        'cand-020',
        'cand-021',
      ])
      const text = norm(w.text())
      expect(text).toContain('Finished · no flags') // cand-001: nothing to flag, so not in the queue
      expect(text).toContain('Sitting now · 7 of 12') // cand-020 has not finished
      expect(text).toContain('Opened, not started') // cand-021
      expect(text).toContain('In queue')
      expect(text).toContain('Decided') // cand-018 arrives with a decision
      expect(norm(w.get('a.q-item[href*="cand-007"]').text())).toContain('3 flags')
      expect(everyoneButton().attributes('aria-pressed')).toBe('true')

      await w.get('a.q-item[href*="cand-001"]').trigger('click')
      await untilText(w, 'Candidate cand-001')

      await w.findAll('.filters button').find((b) => b.text().startsWith('Flagged'))!.trigger('click')
      expect(queueIds(w)).toHaveLength(7)
    })

    it('does not ask for the list of everyone until it is chosen', async () => {
      vi.mocked(api).mockClear() // calls from earlier tests do not count
      const { w } = await renderAt('/review')
      await until(() => queueIds(w).length === 7)
      const asked = () =>
        vi.mocked(api).mock.calls.some(([path]) => String(path).startsWith('/api/review/candidates'))
      expect(asked()).toBe(false)

      await w.findAll('.filters button').find((b) => b.text().startsWith('Everyone'))!.trigger('click')
      await until(() => queueIds(w).length === 10)
      expect(asked()).toBe(true)
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

    it('tells a reviewer when the candidate has already been sent their result email', async () => {
      setMockEmailed(['cand-015'])
      const { w } = await renderAt('/review/candidates/cand-015')
      await untilText(w, 'Candidate cand-015')
      expect(w.text()).not.toContain('already been sent their result email')

      await button(w, 'Add to shortlist')!.trigger('click')
      await untilText(w, 'already been sent their result email')
      expect(w.text()).not.toContain('example.org') // told, never shown an address
    })

    it('says nothing about email when none has gone out', async () => {
      const { w } = await renderAt('/review/candidates/cand-015')
      await untilText(w, 'Candidate cand-015')
      await button(w, 'Add to shortlist')!.trigger('click')
      await until(() => button(w, 'Remove from shortlist') !== undefined)
      expect(w.text()).not.toContain('result email')
    })

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

    it('tells the reviewer when a candidate is not found', async () => {
      const { w } = await renderAt('/review/candidates/cand-999')
      await untilText(w, 'That candidate was not found.')
    })

    it('opens someone the queue leaves out, with their video kept closed', async () => {
      const { w } = await renderAt('/review/candidates/cand-001')
      await untilText(w, 'Candidate cand-001')

      expect(w.text()).toContain('No flags.')
      expect(w.text()).toContain('Video stays closed for candidates who are not in the review queue')
      expect(w.find('.video-card').exists()).toBe(false)
      expect(w.text()).not.toContain('Rank ')
    })

    it('fetches the action log only when asked, then lists the paper and every event', async () => {
      vi.mocked(api).mockClear() // calls from earlier tests do not count
      const { w } = await renderAt('/review/candidates/cand-007')
      await untilText(w, 'Candidate cand-007')
      const askedForLog = () =>
        vi.mocked(api).mock.calls.some(([path]) => String(path).endsWith('/events'))
      expect(askedForLog()).toBe(false)
      expect(w.text()).not.toContain('Everything the page reported')

      await button(w, 'Show the action log')!.trigger('click')
      await untilText(w, 'Everything the page reported')
      expect(askedForLog()).toBe(true)

      const text = norm(w.text())
      expect(text).toContain('8 events')
      expect(text).toContain('24 heartbeats')
      expect(text).toContain('Left the test window')
      expect(text).toContain('Before start') // the page loading comes before the timer ran
      expect(text).toContain('length (characters): 212') // a copy keeps its length, never its text
      expect(text).toContain('Not answered') // a question the candidate never got to
      // the one question an AI wrote for this candidate is marked, with the model in its tooltip
      const tags = w.findAll('#action-log .ai-tag')
      expect(tags).toHaveLength(1)
      expect(tags[0].attributes('title')).toBe('Written by ollama:qwen2.5:7b')
      expect(w.findAll('#action-log tbody tr')).toHaveLength(3 + 8)

      await button(w, 'Hide the action log')!.trigger('click')
      expect(w.text()).not.toContain('Everything the page reported')
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

    it('shows sittings and warns while practice questions are in the bank', async () => {
      const { w } = await renderAt('/admin')
      await untilHeading(w, 'Admin')
      await untilText(w, /60 practice questions are still in the question bank/)
      await untilText(w, 'Synthetic sitting 1')
    })

    it('shows where the setup stands, with a way to the next step', async () => {
      const { w } = await renderAt('/admin')
      await until(() => w.find('#setup-title').exists())
      const setup = w.get('section[aria-labelledby=setup-title]')

      expect(norm(setup.text())).toMatch(/Only practice questions so far \(60\)/)
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
      expect(norm(w.get('#paper-summary').text())).toContain(
        '12 questions from 3 sections. Each question gets 1 minute 45 seconds, so the test takes 21 minutes.',
      )
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
      await w.get('#new-sitting form').trigger('submit')

      await untilText(w, 'Pilot 28 Oct')
      const row = norm(w.findAll('tbody tr').find((r) => r.text().includes('Pilot 28 Oct'))!.text())
      expect(row).toContain('14 min') // 8 questions at 1.75 minutes
      expect(row).toContain('8 questions')
      expect(row).toContain('numerical 4, verbal 4')
    })

    it('says "Not open yet" for a sitting whose time is still ahead, and "Time ended" for one that has passed', async () => {
      const { mockApi } = await import('./mock')
      const hours = (h: number) => new Date(Date.now() + h * 3600_000).toISOString()
      const make = (name: string, opens: string | null, closes: string | null) =>
        mockApi(
          '/api/admin/sittings',
          'POST',
          { name, opens_at: opens, closes_at: closes, per_section: { numerical: 2 }, question_mode: 'practice' },
          'mock-admin:a@b.c',
        )
      await make('Tomorrow', hours(24), hours(72))
      await make('Last week', hours(-200), hours(-100))
      await make('Right now', hours(-1), hours(48))

      const { w } = await renderAt('/admin')
      await untilText(w, 'Tomorrow')
      const pill = (name: string) =>
        norm(w.findAll('tbody tr').find((r) => r.text().includes(name))!.get('.pill').text())
      expect(pill('Tomorrow')).toBe('Not open yet')
      expect(pill('Last week')).toBe('Time ended')
      expect(pill('Right now')).toBe('Open')
      expect(pill('Synthetic sitting 1')).toBe('Open') // no window at all: always open
      expect(pill('Earlier synthetic sitting')).toBe('Closed')
    })

    it('says when a sitting a person is about to invite candidates to is not open yet', async () => {
      const { mockApi } = await import('./mock')
      await mockApi(
        '/api/admin/sittings',
        'POST',
        {
          name: 'Tomorrow',
          opens_at: new Date(Date.now() + 24 * 3600_000).toISOString(),
          closes_at: null,
          per_section: { numerical: 2 },
          question_mode: 'practice',
        },
        'mock-admin:a@b.c',
      )
      const { w } = await renderAt('/admin/invites')
      await until(() => w.find('#sitting').exists())
      await untilText(w, 'This sitting does not open until')
      expect(norm(w.text())).toContain('told when to come back')

      await w.get('#sitting').setValue('1') // the sitting that has no window
      await until(() => !w.text().includes('This sitting does not open until'))
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

  describe('admin: sittings whose questions an AI writes for each candidate', () => {
    beforeEach(asAdmin)

    async function inAiMode() {
      const rendered = await renderAt('/admin')
      await until(() => rendered.w.find('#new-sitting').exists())
      await rendered.w.get('input[name=mode][value=ai]').setValue(true)
      await until(() => rendered.w.find('#ai-numerical').exists())
      return rendered
    }
    const value = (w: VueWrapper, id: string) => (w.get(id).element as HTMLInputElement).value

    it('starts on the practice questions while Cytonn\'s are not loaded, and says how to load them', async () => {
      const { w } = await renderAt('/admin')
      await until(() => w.find('#per-verbal').exists())
      expect((w.get('input[name=mode][value=practice]').element as HTMLInputElement).checked).toBe(true)
      expect(w.find('#ai-numerical').exists()).toBe(false)
      expect(w.text()).not.toContain('Try the writer')

      await w.get('input[name=mode][value=cytonn]').setValue(true)
      await until(() => w.text().includes('not loaded yet'))
      expect(norm(w.text())).toContain('python -m scripts.jobs fetch_cytonn_bank')
      expect(w.find('#per-verbal').exists()).toBe(false) // nothing of Cytonn's to ask for
      expect((button(w, 'Create sitting')!.element as HTMLButtonElement).disabled).toBe(true)
    })

    it('offers all seven kinds of question with a small paper to start from', async () => {
      const { w } = await inAiMode()
      const names = w.findAll('.section-rows .name > span:first-child').map((n) => n.text())
      expect(names).toEqual([
        'Numerical',
        'Verbal',
        'Logical',
        'Critical Thinking',
        'Error Checking',
        'AI Competence',
        'Office Assistant',
      ])
      expect(value(w, '#ai-numerical')).toBe('2')
      expect(value(w, '#ai-office-assistant')).toBe('0')
      expect(norm(w.get('#paper-summary').text())).toContain('6 questions from 3 sections')
      expect(w.text()).toContain('Written by qwen2.5:7b (ollama)')
    })

    it('steps a kind up and down and stops at the most one kind may have', async () => {
      const { w } = await inAiMode()
      await w.get('button[aria-label="More Critical Thinking questions"]').trigger('click')
      expect(value(w, '#ai-critical-thinking')).toBe('1')

      await w.get('#ai-numerical').setValue('99')
      await w.get('#ai-numerical').trigger('change')
      expect(value(w, '#ai-numerical')).toBe('30')
      expect((w.get('button[aria-label="More Numerical questions"]').element as HTMLButtonElement).disabled).toBe(true)
    })

    it('creates a sitting with the chosen numbers and shows that the AI writes it', async () => {
      const { w } = await inAiMode()
      await w.get('#name').setValue('Graduate intake')
      await w.get('#ai-numerical').setValue('6')
      await w.get('#ai-numerical').trigger('change')
      await w.get('#ai-logical').setValue('10')
      await w.get('#ai-logical').trigger('change')
      await w.get('#ai-verbal').setValue('0')
      await w.get('#ai-verbal').trigger('change')
      expect(norm(w.get('#paper-summary').text())).toContain('16 questions from 2 sections')
      await w.get('#new-sitting form').trigger('submit')

      await untilText(w, 'Graduate intake')
      const row = norm(w.findAll('tbody tr').find((r) => r.text().includes('Graduate intake'))!.text())
      expect(row).toContain('16 questions')
      expect(row).toContain('written by AI: numerical 6, logical 10')
    })

    it('says plainly when the writer cannot be reached, and refuses to make the sitting', async () => {
      const { AI_STATUS } = await import('./mock')
      AI_STATUS.available = false
      AI_STATUS.detail = 'Ollama is not running at http://localhost:11434.'
      try {
        const { w } = await inAiMode()
        expect(norm(w.get('#new-sitting .banner').text())).toContain('Ollama is not running')
        await w.get('#name').setValue('No writer')
        await w.get('#new-sitting form').trigger('submit')

        await until(() => w.find('[role=alert]').exists())
        expect(norm(w.get('[role=alert]').text())).toContain('cannot be reached')
        expect(norm(w.get('[role=alert]').text())).toContain('Ollama is not running')
        expect((button(w, 'Write one question')!.element as HTMLButtonElement).disabled).toBe(true)
      } finally {
        AI_STATUS.available = true
        AI_STATUS.detail = 'Ollama (qwen2.5:7b).'
      }
    })

    it('writes one real question on request and shows it with its answer, the working and how it went', async () => {
      const { w } = await inAiMode()
      await w.get('#sample-category').setValue('numerical')
      await w.get('#sample-difficulty').setValue('hard')
      await button(w, 'Write one question')!.trigger('click')

      await until(() => w.find('.sample-card').exists())
      const card = w.get('.sample-card')
      expect(card.text()).toContain('A cyclist rides 36 km in 3 hours')
      expect(card.get('li.right').text()).toContain('12')
      expect(card.get('li.right').text()).toContain('(marked correct)')
      const text = norm(card.text())
      expect(text).toContain('Working: 36 / 3 = 12.')
      expect(text).toContain('hard · written by ollama:qwen2.5:7b in 41.5 s, 2 rounds')
      expect(text).toContain('thrown away on the way: the independent check chose a different answer')
    })

    it('shows what the sitting list needs for papers that failed, and restarts them', async () => {
      const { w } = await inAiMode()
      await w.get('#name').setValue('Needs restart')
      await w.get('#new-sitting form').trigger('submit')
      await untilText(w, 'Needs restart')

      // the list reports one candidate whose questions could not be written
      const { mockApi } = await import('./mock')
      const listed = (await mockApi('/api/admin/sittings', 'GET', undefined, 'mock-admin:a@b.c')) as {
        sittings: { name: string; counts: { papers_failed: number } }[]
      }
      listed.sittings.find((s) => s.name === 'Needs restart')!.counts.papers_failed = 1
      clearQueryClient()
      const again = await renderAt('/admin')
      await untilText(again.w, '1 could not have questions written')

      await button(again.w, 'Write them again')!.trigger('click')
      await untilText(again.w, '1 still having questions written')
      expect(again.w.text()).not.toContain('could not have questions written')
    })
  })

  describe("admin: sittings made from Cytonn's questions", () => {
    beforeEach(() => {
      asAdmin()
      loadCytonnIntoMock()
    })

    it('offers Cytonn\'s questions first once they are loaded, in all seven sections', async () => {
      const { w } = await renderAt('/admin')
      await until(() => w.find('#per-numerical').exists())

      expect((w.get('input[name=mode][value=cytonn]').element as HTMLInputElement).checked).toBe(true)
      const names = w.findAll('.section-rows .name .cap').map((n) => n.text())
      expect(names).toEqual([
        'ai competence',
        'critical thinking',
        'error checking',
        'logical',
        'numerical',
        'office assistant',
        'verbal',
      ])
      expect(norm(w.get('.section-rows').text())).toContain('numerical (563 from Cytonn)')
      expect(norm(w.get('.section-rows').text())).toContain('office assistant (12 from Cytonn)')
      expect((w.get('#per-critical-thinking').element as HTMLInputElement).value).toBe('2')
      expect((w.get('#per-office-assistant').element as HTMLInputElement).value).toBe('2')
      expect(norm(w.get('#paper-summary').text())).toContain('14 questions from 7 sections')
    })

    it('never asks for more of a section than Cytonn has', async () => {
      const { w } = await renderAt('/admin')
      await until(() => w.find('#per-office-assistant').exists())
      await w.get('#per-office-assistant').setValue('99')
      await w.get('#per-office-assistant').trigger('change')
      expect((w.get('#per-office-assistant').element as HTMLInputElement).value).toBe('12')
    })

    it('works the paper\'s time out at 1.75 minutes a question, with nothing to set', async () => {
      const { w } = await renderAt('/admin')
      await until(() => w.find('#paper-summary').exists())
      expect(w.find('#minutes').exists()).toBe(false)
      // 14 questions at 1.75 minutes each is 24.5, so 25
      expect(norm(w.get('#paper-summary').text())).toContain('so the test takes 25 minutes.')

      await w.get('#per-numerical').setValue('10')
      await w.get('#per-numerical').trigger('change') // 22 questions: 38.5 minutes
      expect(norm(w.get('#paper-summary').text())).toContain('so the test takes 39 minutes.')
    })

    it('creates a Cytonn sitting with the chosen sections and time and labels it as such', async () => {
      const { w } = await renderAt('/admin')
      await until(() => w.find('#per-verbal').exists())
      await w.get('#name').setValue('Cytonn intake')
      await w.get('#per-numerical').setValue('6')
      await w.get('#per-numerical').trigger('change')
      await w.get('#per-logical').setValue('0')
      await w.get('#per-logical').trigger('change')
      await w.get('#new-sitting form').trigger('submit')

      await untilText(w, 'Cytonn intake')
      const row = norm(w.findAll('tbody tr').find((r) => r.text().includes('Cytonn intake'))!.text())
      expect(row).toContain('16 questions')
      expect(row).toContain("Cytonn's questions: ai competence 2, critical thinking 2")
      expect(row).toContain('numerical 6')
      expect(row).not.toContain('logical')
      expect(row).toContain('28 min')
    })

    it('keeps practice questions and Cytonn\'s apart: each mode sees only its own', async () => {
      const { w } = await renderAt('/admin')
      await until(() => w.find('#per-numerical').exists())
      await w.get('input[name=mode][value=practice]').setValue(true)
      await until(() => !w.find('#per-critical-thinking').exists())

      expect(w.findAll('.section-rows .name .cap').map((n) => n.text())).toEqual([
        'logical',
        'numerical',
        'verbal',
      ])
      expect(norm(w.get('.section-rows').text())).toContain('numerical (20 in the practice bank)')
      expect(w.find('#cytonn-time').exists()).toBe(false)

      await w.get('input[name=mode][value=cytonn]').setValue(true)
      await until(() => w.find('#per-critical-thinking').exists())
      // what was set for Cytonn is still there
      expect((w.get('#per-numerical').element as HTMLInputElement).value).toBe('2')
    })

    it('does not warn that placeholders can appear on real papers: only practice sittings use them', async () => {
      const { w } = await renderAt('/admin')
      await untilText(w, 'practice questions are still in the question bank')
      expect(norm(w.text())).toContain('Only practice sittings use them')
    })
  })

  describe('admin: invitations', () => {
    beforeEach(asAdmin)

    async function newSitting(name: string, mode: 'ai' | 'practice' = 'practice') {
      const { mockApi } = await import('./mock')
      await mockApi(
        '/api/admin/sittings',
        'POST',
        {
          name,
          opens_at: null,
          closes_at: null,
          per_section: { numerical: 3 },
          question_mode: mode,
        },
        'mock-admin:a@b.c',
      )
    }
    const options = (w: VueWrapper) =>
      w.findAll('#sitting option').map((o) => norm(o.text()))

    it('makes the codes for the sitting picked and says which sitting they are for', async () => {
      const { w } = await renderAt('/admin/invites')
      await until(() => options(w).length > 0)
      expect(options(w)).toEqual(['Synthetic sitting 1 (practice questions, 12 questions, 30 min)'])
      await w.get('#count').setValue('2')
      await w.get('form').trigger('submit')

      await untilText(w, '2 new codes')
      expect(norm(w.text())).toContain('For "Synthetic sitting 1".')
    })

    it('offers every open sitting, newest first, and sends the codes to the one chosen', async () => {
      await newSitting('Cytonn day', 'practice')
      const { w } = await renderAt('/admin/invites')
      await until(() => options(w).length === 2)
      expect(options(w)).toEqual([
        'Cytonn day (practice questions, 3 questions, 5 min)',
        'Synthetic sitting 1 (practice questions, 12 questions, 30 min)',
      ])
      expect((w.get('#sitting').element as HTMLSelectElement).selectedOptions[0].text).toContain('Cytonn day')

      await w.get('#count').setValue('3')
      await w.get('form').trigger('submit')
      await untilText(w, '3 new codes')
      expect(norm(w.text())).toContain('For "Cytonn day".')

      // the candidates list says which sitting each code opens
      await until(() => w.findAll('tbody tr').some((r) => r.text().includes('Cytonn day')))
      const mine = w.findAll('tbody tr').filter((r) => r.text().includes('Cytonn day') && r.text().includes('Not opened'))
      expect(mine.length).toBe(3)
      const older = w.findAll('tbody tr').find((r) => r.text().includes('cand-001'))!
      expect(norm(older.text())).toContain('Synthetic sitting 1')
    })

    it('lets a code be made for an older open sitting by picking it', async () => {
      await newSitting('Cytonn day')
      const { w } = await renderAt('/admin/invites')
      await until(() => options(w).length === 2)
      await w.get('#sitting').setValue(String(1)) // Synthetic sitting 1
      await w.get('form').trigger('submit')
      await untilText(w, 'For "Synthetic sitting 1".')
    })

    it('cannot make codes when no sitting is open, and points to where one is made', async () => {
      const { mockApi } = await import('./mock')
      await mockApi('/api/admin/sittings/1/close', 'POST', { force: true }, 'mock-admin:a@b.c')
      const { w } = await renderAt('/admin/invites')
      await untilText(w, 'No sitting is open.')
      expect(link(w, 'Create one first')!.attributes('href')).toBe('/admin')
      expect((button(w, 'Generate codes')!.element as HTMLButtonElement).disabled).toBe(true)
    })

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

    describe('people with emails', () => {
      const create = (w: Awaited<ReturnType<typeof renderAt>>['w']) =>
        button(w, 'Create invitations and send emails')!.element as HTMLButtonElement

      it('checks a pasted list, then makes one invitation per person with their email', async () => {
        const { w } = await renderAt('/admin/invites')
        await until(() => w.find('#people').exists())
        await w.get('#people').setValue('Ada Lovelace, ada@example.org\nGrace Hopper, grace@navy.test')
        expect(create(w).disabled).toBe(true) // not checked yet

        await button(w, 'Check the list')!.trigger('click')
        await untilText(w, '2 people are ready to invite')
        expect(create(w).disabled).toBe(false)
        await button(w, 'Create invitations and send emails')!.trigger('click')

        await untilText(w, '2 new codes')
        expect(w.text()).toContain('Ada Lovelace')
        expect(w.text()).toContain('ada@example.org')
        expect(button(w, 'Download CSV')).toBeDefined()
        // the candidate list shows the email masked, with the state of the email
        await until(() => w.findAll('tbody tr').some((r) => r.text().includes('a***@example.org')))
        const row = norm(w.findAll('tbody tr').find((r) => r.text().includes('a***@example.org'))!.text())
        expect(row).toContain('Waiting to send')
        expect(row).not.toContain('ada@example.org')
      })

      it('names every bad line and creates nobody until the list is fixed', async () => {
        const { w } = await renderAt('/admin/invites')
        await until(() => w.find('#people').exists())
        await w.get('#people').setValue('Ada Lovelace, ada@example.org\nBob, not-an-email')
        await button(w, 'Check the list')!.trigger('click')

        await untilText(w, 'Fix 1 line before anyone is invited')
        expect(norm(w.get('#list-problems').text())).toContain(
          'Line 2 (Bob, not-an-email) does not have a valid email address.',
        )
        expect(create(w).disabled).toBe(true)

        await w.get('#people').setValue('Ada Lovelace, ada@example.org') // changed: it must be checked again
        expect(w.text()).not.toContain('Fix 1 line')
        expect(create(w).disabled).toBe(true)
      })

      it('says when mail is not set up, and what to do instead', async () => {
        setMockMail({ set_up: false })
        const { w } = await renderAt('/admin/invites')
        await untilText(w, 'Mail is not set up yet')
        expect(w.text()).toContain('docs/plan/email-setup.md')
        expect(w.find('#test-to').exists()).toBe(false)
      })

      it('sends a test email and says what the mail server answered when it refuses', async () => {
        const { w } = await renderAt('/admin/invites')
        await until(() => w.find('#test-to').exists())
        await w.get('#test-to').setValue('me@example.test')
        await button(w, 'Send a test email')!.trigger('click')
        await untilText(w, 'Sent. Check that inbox.')

        setMockMail({ testFails: true })
        await button(w, 'Send a test email')!.trigger('click')
        await untilText(w, 'The mail server said: SMTPAuthenticationError: 535 not accepted')
      })

      it('offers to try failed emails again', async () => {
        setMockMail({ failed: 2 })
        const { w } = await renderAt('/admin/invites')
        await untilText(w, '2 emails could not be sent.')
        await button(w, 'Try them again')!.trigger('click')
        await until(() => !w.text().includes('could not be sent'))
      })
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

  describe("admin: a sitting's own page", () => {
    beforeEach(asAdmin)

    const rows = (w: VueWrapper) => w.findAll('.table tbody tr')
    const row = (w: VueWrapper, id: string) => rows(w).find((r) => r.text().includes(id))!
    const cells = (w: VueWrapper, id: string) => row(w, id).findAll('td').map((td) => norm(td.text()))
    const tile = (w: VueWrapper, name: string) =>
      norm(w.findAll('.tile').find((t) => t.get('h2').text() === name)!.get('.tile-n').text())
    const asAdminApi = async (path: string, method: 'GET' | 'POST', body?: unknown) => {
      const { mockApi } = await import('./mock')
      return mockApi(path, method, body, 'mock-admin:a@b.c')
    }
    const newSitting = (name: string, mode: 'ai' | 'practice' = 'practice') =>
      asAdminApi('/api/admin/sittings', 'POST', {
        name,
        opens_at: null,
        closes_at: null,
        per_section: { numerical: 2 },
        question_mode: mode,
      })

    it('opens from a click on the sitting row, and from the name as a plain link', async () => {
      const { w, router } = await renderAt('/admin')
      await untilText(w, 'Synthetic sitting 1')
      expect(link(w, 'Synthetic sitting 1')!.attributes('href')).toBe('/admin/sittings/1')

      await w.findAll('tbody tr').find((r) => r.text().includes('Synthetic sitting 1'))!.trigger('click')
      await until(() => router.currentRoute.value.path === '/admin/sittings/1')
      await until(() => w.find('#sitting-name').exists())
      expect(w.get('#sitting-name').text()).toBe('Synthetic sitting 1')
      expect(tab(w, 'Sitting setup')!.attributes('aria-current')).toBe('page')
    })

    it('does not open the sitting when a button inside its row is pressed', async () => {
      const { w, router } = await renderAt('/admin')
      await until(() => button(w, 'Close sitting') !== undefined)
      await button(w, 'Close sitting')!.trigger('click')
      await until(() => button(w, 'Close anyway (logged)') !== undefined)
      expect(router.currentRoute.value.path).toBe('/admin')
    })

    it('shows who has done the test and who has not, and filters by it', async () => {
      const { w } = await renderAt('/admin/sittings/1')
      await until(() => rows(w).length === 20)

      expect(tile(w, 'Invited')).toBe('20')
      expect(tile(w, 'Not opened')).toBe('4')
      expect(tile(w, 'Opened')).toBe('0')
      expect(tile(w, 'Sitting now')).toBe('2')
      expect(tile(w, 'Finished')).toBe('14')
      expect(cells(w, 'cand-001').slice(0, 3)).toEqual(['cand-001', 'Finished', '12 of 12'])
      expect(cells(w, 'cand-015').slice(0, 3)).toEqual(['cand-015', 'Sitting now', '6 of 12'])
      expect(cells(w, 'cand-020').slice(0, 3)).toEqual(['cand-020', 'Not opened', '-'])

      await filterButton(w, 'Not opened 4').trigger('click')
      expect(rows(w).map((r) => r.get('td').text())).toEqual(['cand-017', 'cand-018', 'cand-019', 'cand-020'])
      await filterButton(w, 'Finished 14').trigger('click')
      expect(rows(w)).toHaveLength(14)
      await filterButton(w, 'All 20').trigger('click')
      expect(rows(w)).toHaveLength(20)
    })

    it('says a sitting does not exist, rather than showing nothing', async () => {
      const { w } = await renderAt('/admin/sittings/999')
      await untilText(w, 'That sitting does not exist')
      expect(link(w, 'Back to the sittings')!.attributes('href')).toBe('/admin')
    })

    it('makes invitations for this sitting: the link carries which one, and the page picks it', async () => {
      await newSitting('Newer sitting')
      const { w } = await renderAt('/admin/sittings/1')
      await until(() => link(w, 'Make invitations') !== undefined)
      expect(link(w, 'Make invitations')!.attributes('href')).toBe('/admin/invites?sitting=1')

      const invites = await renderAt('/admin/invites?sitting=1')
      await until(() => invites.w.findAll('#sitting option').length === 2)
      expect((invites.w.get('#sitting').element as HTMLSelectElement).value).toBe('1')
    })

    it('offers a new link to anyone in an open sitting, a finished candidate included', async () => {
      const { w } = await renderAt('/admin/sittings/1')
      await until(() => rows(w).length === 20)
      // a forgotten password is fixed by a new link, so someone who has finished (and may still have
      // a recording to send) gets the button too
      expect(w.find('button[aria-label="Resend link to cand-001"]').exists()).toBe(true)
      expect(w.get('button[aria-label="Resend link to cand-016"]').attributes('title')).toContain(
        'clears their password',
      )

      await w.get('button[aria-label="Resend link to cand-016"]').trigger('click')
      await until(() => w.find('.tokenbox').exists())
      expect(w.get('.tokenbox').text()).toContain('cand-016')
      expect(w.get('.tokenbox code').text()).toMatch(/\/\?t=[0-9A-Z]{4}-[0-9A-Z]{4}$/)
    })

    it('closes the sitting from its page, asking first when people have not finished', async () => {
      const { w } = await renderAt('/admin/sittings/1')
      await until(() => button(w, 'Close sitting') !== undefined)
      await button(w, 'Close sitting')!.trigger('click')
      await until(() => button(w, 'Close anyway (logged)') !== undefined)
      expect(norm(w.text())).toContain('6 not finished.')

      await button(w, 'Close anyway (logged)')!.trigger('click')
      await until(() => w.get('#sitting-name').element.parentElement!.textContent!.includes('Closed'))
      expect(link(w, 'Make invitations')).toBeUndefined()
      expect(button(w, 'Close sitting')).toBeUndefined()
    })

    describe('deleting a sitting', () => {
      async function throwaway() {
        await newSitting('Throwaway')
        await asAdminApi('/api/admin/invites', 'POST', { count: 3, sitting_id: 3 })
        const rendered = await renderAt('/admin/sittings/3')
        await until(() => rows(rendered.w).length === 3)
        return rendered
      }

      it('asks for the name, says what goes with it, and only then deletes', async () => {
        const { w, router } = await throwaway()
        expect(w.find('#confirm-name').exists()).toBe(false)

        await button(w, 'Delete sitting')!.trigger('click')
        const panel = norm(w.get('section[aria-labelledby=delete-title]').text())
        expect(panel).toContain('Delete "Throwaway"?')
        expect(panel).toContain('3 invitations')
        expect(panel).toContain('This cannot be undone')
        const go = () => button(w, 'Delete for good')!.element as HTMLButtonElement
        expect(go().disabled).toBe(true)

        await w.get('#confirm-name').setValue('throwaway')
        expect(go().disabled).toBe(true) // the name is typed as it is written
        await w.get('#confirm-name').setValue('Throwaway')
        expect(go().disabled).toBe(false)

        await w.get('section[aria-labelledby=delete-title] form').trigger('submit')
        await until(() => router.currentRoute.value.path === '/admin')
        await untilText(w, 'Synthetic sitting 1')
        expect(w.text()).not.toContain('Throwaway')
        // and the audit log has a line for it
        const { mockApi } = await import('./mock')
        const audit = (await mockApi('/api/review/audit', 'GET', undefined, 'mock-admin:a@b.c')) as {
          entries: { detail: string }[]
        }
        expect(audit.entries.some((e) => e.detail.startsWith('deleted sitting "Throwaway"'))).toBe(true)
      })

      it('can be cancelled', async () => {
        const { w } = await throwaway()
        await button(w, 'Delete sitting')!.trigger('click')
        await button(w, 'Cancel')!.trigger('click')
        expect(w.find('#confirm-name').exists()).toBe(false)
        expect(w.find('#sitting-name').exists()).toBe(true)
      })

      it('is refused while a test is running, and says so in words', async () => {
        const { w, router } = await renderAt('/admin/sittings/1')
        await until(() => rows(w).length === 20)
        await button(w, 'Delete sitting')!.trigger('click')
        await w.get('#confirm-name').setValue('Synthetic sitting 1')
        await w.get('section[aria-labelledby=delete-title] form').trigger('submit')

        await until(() => w.find('section[aria-labelledby=delete-title] [role=alert]').exists())
        expect(norm(w.get('section[aria-labelledby=delete-title] [role=alert]').text())).toBe(
          '2 candidates are in the middle of the test. Wait until they finish or their time runs out, then try again.',
        )
        expect(router.currentRoute.value.path).toBe('/admin/sittings/1')
        expect(rows(w)).toHaveLength(20)
      })
    })

    it('shows how long each AI paper has been waited for, and restarts the stuck ones', async () => {
      await newSitting('AI day', 'ai')
      await asAdminApi('/api/admin/invites', 'POST', { count: 3, sitting_id: 3 })
      const { patchMockInvitee } = await import('./mock')
      patchMockInvitee('cand-021', {
        status: 'opened',
        paper: { paper_status: 'pending', paper_error: null, waited_s: 700 },
      })
      patchMockInvitee('cand-022', {
        status: 'opened',
        paper: { paper_status: 'failed', paper_error: 'ollama is not running', waited_s: null },
      })
      patchMockInvitee('cand-023', { status: 'opened' })

      const { w } = await renderAt('/admin/sittings/3')
      await until(() => rows(w).length === 3)

      // candidate, status, answered, questions
      expect(cells(w, 'cand-021')[3]).toBe('Being written, waited 11 min')
      expect(cells(w, 'cand-022')[3]).toBe('Could not be writtenollama is not running')
      expect(cells(w, 'cand-023')[3]).toBe('Ready')
      expect(button(w, 'Write them again (2)')).toBeDefined()
    })

    it('has no Questions column for a sitting that is not written by AI', async () => {
      const { w } = await renderAt('/admin/sittings/1')
      await until(() => rows(w).length === 20)
      expect(w.findAll('th').map((th) => th.text())).not.toContain('Questions')
    })

    describe('result emails', () => {
      it('shows who is ready for each email and asks before sending the pass emails', async () => {
        const { w } = await renderAt('/admin/sittings/1')
        await untilText(w, 'Result emails')
        expect(norm(w.text())).toContain('3 ready for a pass email (0 already sent)')
        expect(norm(w.get('#held-back').text())).toContain('1 held back until a person decides: cand-007')
        expect(norm(w.text())).toContain('2 did not finish and get no email')
        // the sitting is still open, so no one can be told they did not pass yet
        expect((button(w, 'Send not-passed emails (5)')!.element as HTMLButtonElement).disabled).toBe(true)
        expect(w.text()).toContain('Close the sitting first.')

        await button(w, 'Send pass emails (3)')!.trigger('click')
        expect(norm(w.text())).toContain('Send 3 pass emails now? An email cannot be taken back.')
        await button(w, 'Yes, send')!.trigger('click')

        await untilText(w, '3 pass emails are queued')
        expect(norm(w.text())).toContain('0 ready for a pass email (3 already sent)')
      })

      it('can cancel at the question and sends nothing', async () => {
        const { w } = await renderAt('/admin/sittings/1')
        await untilText(w, 'Result emails')
        await button(w, 'Send pass emails (3)')!.trigger('click')
        await button(w, 'Cancel')!.trigger('click')
        expect(button(w, 'Send pass emails (3)')).toBeDefined()
        expect(w.text()).not.toContain('are queued')
      })

      it('lets the not-passed emails go once the sitting is closed', async () => {
        const { w } = await renderAt('/admin/sittings/2') // the closed one
        await untilText(w, 'Result emails')
        expect((button(w, 'Send not-passed emails (5)')!.element as HTMLButtonElement).disabled).toBe(false)
        await button(w, 'Send not-passed emails (5)')!.trigger('click')
        await button(w, 'Yes, send')!.trigger('click')
        await untilText(w, '5 not-passed emails are queued')
      })

      it('has nothing to send when nobody is ready', async () => {
        setMockResults({ passed: 0, not_passed: 0, held_back: [] })
        const { w } = await renderAt('/admin/sittings/2')
        await untilText(w, 'Result emails')
        expect((button(w, 'Send pass emails (0)')!.element as HTMLButtonElement).disabled).toBe(true)
        expect(w.find('#held-back').exists()).toBe(false)
      })

      it('lets an admin read both emails before sending', async () => {
        const { w } = await renderAt('/admin/sittings/1')
        await untilText(w, 'Result emails')
        expect(w.get('details').text()).toContain('You passed.')
        expect(w.get('details').text()).toContain("Dear [candidate's name],")
        expect(w.get('details').text()).toContain('Not this time.')
      })
    })
  })

  describe('admin: question bank', () => {
    beforeEach(asAdmin)

    it('shows what is in the bank and offers to remove the placeholders', async () => {
      const { w } = await renderAt('/admin/questions')
      await untilText(w, /60 questions: 0 from Cytonn, 60/)
      await button(w, 'Remove practice questions')!.trigger('click')
      expect(button(w, 'Yes, remove 60 practice questions')).toBeDefined()
      await button(w, 'Cancel')!.trigger('click')
      expect(button(w, 'Yes, remove 60 practice questions')).toBeUndefined()
    })

    it('lists the questions a page at a time, and says the correct share is pending', async () => {
      const { w } = await renderAt('/admin/questions')
      await until(() => w.findAll('#all-questions ~ * tbody tr, .panel tbody tr').length > 0)
      await untilText(w, 'Showing 60 of 60.')
      const rows = w.findAll('section[aria-labelledby=all-questions] tbody tr')
      expect(rows).toHaveLength(60)
      expect(norm(rows[0].text())).toContain('Pending')
      expect(norm(rows[0].text())).toContain('Practice')
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
