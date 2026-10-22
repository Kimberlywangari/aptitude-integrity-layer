import { describe, expect, it } from 'vitest'
import { CANDIDATE_PATH, homeFor, LOGIN_PATH, loginPathFor, safeNext } from '../src/lib/routes'

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
    expect(loginPathFor('/overview')).toBe('/login/reviewer')
    expect(loginPathFor('/review/candidates/cand-007')).toBe('/login/reviewer')
    expect(loginPathFor('/administrators')).toBe('/login/reviewer') // not an admin page
  })

  it('only returns to staff pages', () => {
    expect(safeNext('/review')).toBe('/review')
    expect(safeNext('/overview?sitting=2')).toBe('/overview?sitting=2')
    expect(safeNext('/review/candidates/cand-007')).toBe('/review/candidates/cand-007')
    expect(safeNext('/admin?x=1')).toBe('/admin?x=1')
    expect(safeNext('/reviewer-evil')).toBeNull()
    expect(safeNext('/overviews')).toBeNull()
    expect(safeNext('//evil.example.com')).toBeNull()
    expect(safeNext('https://evil.example.com/review')).toBeNull()
    expect(safeNext('/candidate')).toBeNull()
    expect(safeNext(null)).toBeNull()
  })
})
