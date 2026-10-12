import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { api, ApiError, pathForError, setSebRequiredHandler } from '../src/lib/api'
import { clearSession, getAccessToken, saveSession } from '../src/lib/session'

function respond(status: number, body?: unknown) {
  return Promise.resolve(
    new Response(body === undefined ? null : JSON.stringify(body), {
      status,
      headers: { 'Content-Type': 'application/json' },
    }),
  )
}

describe('api()', () => {
  const fetchMock = vi.fn()

  beforeEach(() => {
    vi.stubGlobal('fetch', fetchMock)
    clearSession()
  })

  afterEach(() => {
    fetchMock.mockReset()
    setSebRequiredHandler(null)
    vi.unstubAllGlobals()
  })

  it('sends the bearer token and a JSON body', async () => {
    saveSession('s1', 'tok')
    fetchMock.mockReturnValue(respond(200, { done: false }))

    await api('/api/session/s1/answer', { method: 'POST', body: { position: 1, option_id: 7 } })

    const [path, init] = fetchMock.mock.calls[0]
    expect(path).toBe('/api/session/s1/answer')
    expect(init.method).toBe('POST')
    expect(init.headers.Authorization).toBe('Bearer tok')
    expect(init.headers['Content-Type']).toBe('application/json')
    expect(JSON.parse(init.body)).toEqual({ position: 1, option_id: 7 })
  })

  it('sends no Authorization header before a session exists', async () => {
    fetchMock.mockReturnValue(respond(200, {}))
    await api('/api/health')
    expect(fetchMock.mock.calls[0][1].headers.Authorization).toBeUndefined()
  })

  it('returns undefined for 204', async () => {
    fetchMock.mockReturnValue(respond(204))
    await expect(api('/api/session/s1/self-report', { method: 'POST', body: {} })).resolves.toBeUndefined()
  })

  it('throws ApiError carrying the server code and extra fields', async () => {
    fetchMock.mockReturnValue(respond(409, { code: 'not_current', current_position: 4 }))
    const error = await api('/x').catch((e: unknown) => e)
    expect(error).toBeInstanceOf(ApiError)
    expect((error as ApiError).status).toBe(409)
    expect((error as ApiError).code).toBe('not_current')
    expect((error as ApiError).body.current_position).toBe(4)
  })

  it('maps 403 seb_required to the registered handler and still throws', async () => {
    const handler = vi.fn()
    setSebRequiredHandler(handler)
    fetchMock.mockReturnValue(respond(403, { code: 'seb_required' }))

    await expect(api('/api/session/start', { method: 'POST', body: {} })).rejects.toBeInstanceOf(ApiError)
    expect(handler).toHaveBeenCalledOnce()
  })

  it('does not call the SEB handler for other 403s', async () => {
    const handler = vi.fn()
    setSebRequiredHandler(handler)
    fetchMock.mockReturnValue(respond(403, { code: 'no_open_sitting' }))
    await api('/x').catch(() => undefined)
    expect(handler).not.toHaveBeenCalled()
  })
})

describe('pathForError()', () => {
  const err = (code: string) => new ApiError(409, code, {})

  it('routes "wrong place" errors back into the flow', () => {
    expect(pathForError(err('not_started'))).toBe('/integrity')
    expect(pathForError(err('finished'))).toBe('/done')
    expect(pathForError(err('time_up'))).toBe('/done')
    expect(pathForError(err('unauthorized'))).toBe('/')
  })

  it('leaves everything else to the caller', () => {
    expect(pathForError(err('not_current'))).toBeNull()
    expect(pathForError(new Error('network'))).toBeNull()
  })
})

describe('session storage', () => {
  beforeEach(() => clearSession())

  it('round-trips and clears', () => {
    saveSession('s1', 'tok')
    expect(getAccessToken()).toBe('tok')
    clearSession()
    expect(getAccessToken()).toBeNull()
  })

  it('does not throw when storage is unavailable', () => {
    const spy = vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => {
      throw new Error('blocked')
    })
    expect(getAccessToken()).toBeNull()
    spy.mockRestore()
  })
})
