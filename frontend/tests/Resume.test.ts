import { flushPromises } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { HELP_CONTACT, RESUME_ERRORS, START_ERRORS, START_FALLBACK_ERROR } from '../src/candidate/copy'
import Resume from '../src/candidate/Resume.vue'
import { api, ApiError } from '../src/lib/api'
import { clearSession, getAccessToken, getSessionId } from '../src/lib/session'
import { mountPage } from './helpers/render'

vi.mock('../src/lib/api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../src/lib/api')>()
  return { ...actual, api: vi.fn() }
})

const pages = { '/resume': Resume, '/uploading': 'uploading page' }

async function renderPage(entry = '/resume') {
  return (await mountPage(entry, pages)).wrapper
}

async function submit(w: Awaited<ReturnType<typeof renderPage>>, code: string) {
  await w.get('#invitation').setValue(code)
  await w.get('form').trigger('submit')
  await flushPromises()
}

const resumed = { session_id: 's9', access_token: 'upload-token', status: 'finished', expires_at: '2026-10-21T10:00:00Z' }
const sentToken = () => (vi.mocked(api).mock.calls[0][1] as { body: { token: string } }).body.token

describe('Resume (finishing the upload of a test that is over)', () => {
  beforeEach(() => {
    clearSession()
    vi.mocked(api).mockReset()
  })

  afterEach(() => {
    document.body.innerHTML = ''
    clearSession()
  })

  it('swaps a typed code for an upload key, keeps it as the session, and goes to the upload page', async () => {
    vi.mocked(api).mockResolvedValue(resumed)
    const w = await renderPage()
    await submit(w, 'abcd-efgh')

    expect(vi.mocked(api).mock.calls[0][0]).toBe('/api/session/resume')
    expect(vi.mocked(api).mock.calls[0][1]).toMatchObject({ method: 'POST' })
    expect(sentToken()).toBe('ABCDEFGH') // the same forgiving reading of the code as the start page
    expect(getSessionId()).toBe('s9')
    expect(getAccessToken()).toBe('upload-token')
    expect(w.text()).toContain('uploading page')
  })

  it('does it by itself from an invitation link', async () => {
    vi.mocked(api).mockResolvedValue(resumed)
    const w = await renderPage('/resume?t=ABCD-EFGH')
    await flushPromises()
    expect(sentToken()).toBe('ABCDEFGH')
    expect(w.text()).toContain('uploading page')
  })

  it('does not let the button be pressed with an empty code', async () => {
    const w = await renderPage()
    expect((w.get('button[type=submit]').element as HTMLButtonElement).disabled).toBe(true)
  })

  it.each(Object.entries(RESUME_ERRORS))('explains %s plainly, with who to contact', async (code, message) => {
    vi.mocked(api).mockRejectedValue(new ApiError(409, code, {}))
    const w = await renderPage()
    await submit(w, 'ABCDEFGH')

    expect(w.get('[role=alert]').text()).toContain(message)
    expect(w.get('[role=alert]').text()).toContain(HELP_CONTACT)
    expect(w.text()).not.toContain('uploading page')
  })

  it('says when the code is wrong', async () => {
    vi.mocked(api).mockRejectedValue(new ApiError(401, 'invalid_invitation', {}))
    const w = await renderPage()
    await submit(w, 'WRONG')
    expect(w.get('[role=alert]').text()).toContain(START_ERRORS.invalid_invitation)
  })

  it('tells a throttled candidate how long to wait', async () => {
    vi.mocked(api).mockRejectedValue(new ApiError(429, 'too_many_attempts', { retry_after_s: 90 }))
    const w = await renderPage()
    await submit(w, 'WRONG')
    expect(w.get('[role=alert]').text()).toMatch(/Too many wrong codes\. Please wait .*minute/)
  })

  it('falls back to a plain message for anything unexpected, and allows another try', async () => {
    vi.mocked(api).mockRejectedValueOnce(new Error('offline'))
    const w = await renderPage()
    await submit(w, 'ABCDEFGH')
    expect(w.get('[role=alert]').text()).toContain(START_FALLBACK_ERROR)

    vi.mocked(api).mockResolvedValue(resumed)
    await submit(w, 'ABCDEFGH')
    expect(w.text()).toContain('uploading page')
  })
})
