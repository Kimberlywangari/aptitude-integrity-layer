import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { api, ApiError, pathForError, staffRecovery } from '../src/lib/api'
import { clearSession, saveSession } from '../src/lib/session'
import { clearStaff, getStaff, saveStaff } from '../src/lib/staffSession'

describe('api() token choice', () => {
  const fetchMock = vi.fn()

  beforeEach(() => {
    vi.stubGlobal('fetch', fetchMock)
    fetchMock.mockImplementation(() => Promise.resolve(new Response('{}', { status: 200 })))
    saveSession('s1', 'candidate-token')
    saveStaff({ token: 'staff-token', email: 'r@example.com', role: 'reviewer' })
  })

  afterEach(() => {
    fetchMock.mockReset()
    vi.unstubAllGlobals()
    clearSession()
    clearStaff()
  })

  it('sends the staff token to /api/review and /api/admin', async () => {
    await api('/api/review/queue')
    await api('/api/admin/sittings')
    expect(fetchMock.mock.calls[0][1].headers.Authorization).toBe('Bearer staff-token')
    expect(fetchMock.mock.calls[1][1].headers.Authorization).toBe('Bearer staff-token')
  })

  it('keeps sending the candidate token everywhere else', async () => {
    await api('/api/session/s1/question')
    expect(fetchMock.mock.calls[0][1].headers.Authorization).toBe('Bearer candidate-token')
  })
})

describe('fixture mode', () => {
  const fetchMock = vi.fn()

  beforeEach(() => {
    vi.stubGlobal('fetch', fetchMock)
    fetchMock.mockImplementation(() =>
      Promise.resolve(new Response('{"token":"t","email":"r@example.com","role":"reviewer"}')),
    )
    vi.stubEnv('VITE_MOCK_API', '1') // read when the module loads, so load it again below
    vi.resetModules()
    saveStaff({ token: 'staff-token', email: 'r@example.com', role: 'reviewer' })
  })

  afterEach(() => {
    fetchMock.mockReset()
    vi.unstubAllGlobals()
    vi.unstubAllEnvs()
    vi.resetModules()
    clearStaff()
  })

  it('sends sign-in and me to the real server while the rest of /api/review is mocked', async () => {
    const { api: fixtureApi } = await import('../src/lib/api')
    const { setMockLatency } = await import('../src/lib/mock')
    setMockLatency(0)

    await fixtureApi('/api/review/login', { method: 'POST', body: { email: 'a', password: 'b' } })
    await fixtureApi('/api/review/me')
    expect(fetchMock.mock.calls.map((call) => call[0])).toEqual([
      '/api/review/login',
      '/api/review/me',
    ])

    fetchMock.mockClear()
    await fixtureApi('/api/review/queue') // still a fixture: no request leaves the page
    expect(fetchMock).not.toHaveBeenCalled()
  })

  it('sends the setup screens to the real server', async () => {
    const { api: fixtureApi } = await import('../src/lib/api')

    await fixtureApi('/api/admin/sittings')
    await fixtureApi('/api/admin/invites', { method: 'POST', body: { count: 2 } })
    await fixtureApi('/api/admin/questions/summary')
    expect(fetchMock.mock.calls.map((call) => call[0])).toEqual([
      '/api/admin/sittings',
      '/api/admin/invites',
      '/api/admin/questions/summary',
    ])
    expect(fetchMock.mock.calls[0][1].headers.Authorization).toBe('Bearer staff-token')
  })
})

describe('error routing', () => {
  const err = (status: number, code: string) => new ApiError(status, code, {})

  it('sends a missing pre-check back to /precheck', () => {
    expect(pathForError(err(409, 'precheck_required'))).toBe('/precheck')
  })

  it('has signed-out staff sign in again, and sends the under-privileged home', () => {
    expect(staffRecovery(err(401, 'unauthorized'))).toBe('sign-in')
    expect(staffRecovery(err(401, 'invalid_credentials'))).toBe('sign-in')
    expect(staffRecovery(err(403, 'forbidden'))).toBe('home')
    expect(staffRecovery(err(422, 'reason_too_short'))).toBeNull()
    expect(staffRecovery(new Error('network'))).toBeNull()
  })
})

describe('staff session storage', () => {
  beforeEach(() => clearStaff())

  it('round-trips and clears', () => {
    saveStaff({ token: 't', email: 'a@example.com', role: 'admin' })
    expect(getStaff()).toEqual({ token: 't', email: 'a@example.com', role: 'admin' })
    clearStaff()
    expect(getStaff()).toBeNull()
  })

  it('ignores a damaged value and does not throw when storage is blocked', () => {
    sessionStorage.setItem('integrity.staff', '{"token":1}')
    expect(getStaff()).toBeNull()
    const spy = vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => {
      throw new Error('blocked')
    })
    expect(getStaff()).toBeNull()
    spy.mockRestore()
  })
})
