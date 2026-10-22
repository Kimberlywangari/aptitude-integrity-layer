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

// Every screen talks to the real server. The fixtures in src/lib/mock are for the screen tests.
describe('no fixtures in the app', () => {
  const fetchMock = vi.fn()

  beforeEach(() => {
    vi.stubGlobal('fetch', fetchMock)
    fetchMock.mockImplementation(() =>
      Promise.resolve(new Response('{"token":"t","email":"r@example.com","role":"reviewer"}')),
    )
    saveStaff({ token: 'staff-token', email: 'r@example.com', role: 'reviewer' })
    saveSession('s1', 'candidate-token')
  })

  afterEach(() => {
    fetchMock.mockReset()
    vi.unstubAllGlobals()
    clearStaff()
    clearSession()
  })

  it('sends sign-in and every reviewer screen to the real server', async () => {
    const fixtureApi = api

    await fixtureApi('/api/review/login', { method: 'POST', body: { email: 'a', password: 'b' } })
    await fixtureApi('/api/review/me')
    await fixtureApi('/api/review/queue?sitting=2')
    await fixtureApi('/api/review/candidates/sim-001')
    await fixtureApi('/api/review/audit')
    expect(fetchMock.mock.calls.map((call) => call[0])).toEqual([
      '/api/review/login',
      '/api/review/me',
      '/api/review/queue?sitting=2',
      '/api/review/candidates/sim-001',
      '/api/review/audit',
    ])
    expect(fetchMock.mock.calls[2][1].headers.Authorization).toBe('Bearer staff-token')
  })

  it('sends the pre-check, complaints, events, heartbeat and chunks to the real server too', async () => {
    await api('/api/precheck/result', { method: 'POST', body: { camera_ok: true, mic_ok: true } })
    await api('/api/complaints', { method: 'POST', body: { category: 'other', text: 'x' } })
    await api('/api/chunks/s1/manifest')
    await api('/api/events', { method: 'POST', body: { events: [] } })
    await api('/api/heartbeat', { method: 'POST' })
    expect(fetchMock.mock.calls.map((call) => call[0])).toEqual([
      '/api/precheck/result',
      '/api/complaints',
      '/api/chunks/s1/manifest',
      '/api/events',
      '/api/heartbeat',
    ])
    expect(fetchMock.mock.calls[0][1].headers.Authorization).toBe('Bearer candidate-token')
  })

  it('sends the setup screens to the real server', async () => {
    const fixtureApi = api

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
    expect(pathForError(new ApiError(409, 'precheck_required', { reason: 'precheck' }))).toBe('/precheck')
  })

  it('keeps a candidate where they are when only the recording is missing', () => {
    // the camera check cannot fix a recording that has not reached the server yet
    expect(pathForError(new ApiError(409, 'precheck_required', { reason: 'recording' }))).toBeNull()
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
