import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { api, ApiError, pathForError, staffPathForError } from '../src/lib/api'
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

describe('error routing', () => {
  const err = (status: number, code: string) => new ApiError(status, code, {})

  it('sends a missing pre-check back to /precheck', () => {
    expect(pathForError(err(409, 'precheck_required'))).toBe('/precheck')
  })

  it('sends signed-out staff to the login page and others to the queue', () => {
    expect(staffPathForError(err(401, 'unauthorized'))).toBe('/review/login')
    expect(staffPathForError(err(403, 'forbidden'))).toBe('/review')
    expect(staffPathForError(err(422, 'reason_too_short'))).toBeNull()
    expect(staffPathForError(new Error('network'))).toBeNull()
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
