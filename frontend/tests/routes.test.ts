import { describe, expect, it } from 'vitest'
import { CANDIDATE_PATH, homeFor, LOGIN_PATH, loginPathFor, safeNext } from '../src/lib/routes'
import { crumbsFor } from '../src/staff/crumbs'

describe('routes', () => {
  it('names the three doors', () => {
    expect(CANDIDATE_PATH).toBe('/candidate')
    expect(LOGIN_PATH).toEqual({ reviewer: '/login/reviewer', admin: '/login/admin' })
  })

  it('starts each role on its own page', () => {
    expect(homeFor('reviewer')).toBe('/review')
    expect(homeFor('admin')).toBe('/admin')
  })

  it('asks for the admin sign-in only on admin pages', () => {
    expect(loginPathFor('/admin')).toBe('/login/admin')
    expect(loginPathFor('/admin/invites')).toBe('/login/admin')
    expect(loginPathFor('/review')).toBe('/login/reviewer')
    expect(loginPathFor('/review/candidates/cand-007')).toBe('/login/reviewer')
    expect(loginPathFor('/administrators')).toBe('/login/reviewer') // not an admin page
  })

  it('only returns to staff pages', () => {
    expect(safeNext('/review')).toBe('/review')
    expect(safeNext('/review/candidates/cand-007')).toBe('/review/candidates/cand-007')
    expect(safeNext('/admin?x=1')).toBe('/admin?x=1')
    expect(safeNext('/reviewer-evil')).toBeNull()
    expect(safeNext('//evil.example.com')).toBeNull()
    expect(safeNext('https://evil.example.com/review')).toBeNull()
    expect(safeNext('/candidate')).toBeNull()
    expect(safeNext(null)).toBeNull()
  })
})

describe('breadcrumbs', () => {
  it('has one crumb at the top of a section, which the page then leaves out', () => {
    expect(crumbsFor('/review')).toEqual([{ label: 'Review' }])
    expect(crumbsFor('/admin')).toEqual([{ label: 'Sittings' }])
  })

  it('puts a deeper page under its section', () => {
    expect(crumbsFor('/review/audit')).toEqual([
      { label: 'Review', to: '/review' },
      { label: 'Audit' },
    ])
    expect(crumbsFor('/review/candidates/cand-007')).toEqual([
      { label: 'Review', to: '/review' },
      { label: 'Candidate cand-007' },
    ])
    expect(crumbsFor('/admin/invites')).toEqual([
      { label: 'Admin', to: '/admin' },
      { label: 'Invites' },
    ])
    expect(crumbsFor('/admin/questions')).toEqual([
      { label: 'Admin', to: '/admin' },
      { label: 'Questions' },
    ])
  })

  it('shows an address it cannot decode as typed, and ignores a trailing slash', () => {
    expect(crumbsFor('/review/candidates/100%')[1]).toEqual({ label: 'Candidate 100%' })
    expect(crumbsFor('/admin/invites/')).toHaveLength(2)
  })

  it('has nothing for pages outside the staff app', () => {
    expect(crumbsFor('/candidate')).toEqual([])
  })
})
