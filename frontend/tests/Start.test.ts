import { flushPromises } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { HELP_CONTACT } from '../src/candidate/copy'
import Start from '../src/candidate/Start.vue'
import { api, ApiError } from '../src/lib/api'
import { clearSession, getSessionId } from '../src/lib/session'
import { mountPage } from './helpers/render'

vi.mock('../src/lib/api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../src/lib/api')>()
  return { ...actual, api: vi.fn() }
})

const pages = {
  '/': Start,
  '/precheck': 'precheck page',
  '/test': 'test page',
  '/done': 'done page',
  '/uploading': 'uploading page',
}

async function renderStart(entry = '/') {
  return (await mountPage(entry, pages)).wrapper
}

async function submit(wrapper: Awaited<ReturnType<typeof renderStart>>, code: string) {
  await wrapper.get('#invitation').setValue(code)
  await wrapper.get('form').trigger('submit')
  await flushPromises()
}

const sentToken = () => (vi.mocked(api).mock.calls[0][1] as { body: { token: string } }).body.token

describe('Start', () => {
  beforeEach(() => {
    clearSession()
    vi.mocked(api).mockReset()
  })

  afterEach(() => {
    document.body.innerHTML = ''
    clearSession()
  })

  it('sends a typed code in its canonical form and goes to the device check', async () => {
    vi.mocked(api).mockResolvedValue({ session_id: 's1', access_token: 'tok', status: 'created' })
    const wrapper = await renderStart()
    await submit(wrapper, 'abcd-efgh')

    expect(wrapper.text()).toContain('precheck page')
    expect(vi.mocked(api).mock.calls[0][0]).toBe('/api/session/start')
    expect(sentToken()).toBe('ABCDEFGH')
    expect(getSessionId()).toBe('s1')
  })

  it('reads O and I as 0 and 1', async () => {
    vi.mocked(api).mockResolvedValue({ session_id: 's1', access_token: 'tok', status: 'created' })
    const wrapper = await renderStart()
    await submit(wrapper, 'OO11-ABCD')
    expect(sentToken()).toBe('0011ABCD')
  })

  it('leaves a long token from the first seed as it was', async () => {
    vi.mocked(api).mockResolvedValue({ session_id: 's1', access_token: 'tok', status: 'created' })
    const wrapper = await renderStart()
    await submit(wrapper, 'a3f9c1d2e4b5a6f7c8d9e0f1')
    expect(sentToken()).toBe('a3f9c1d2e4b5a6f7c8d9e0f1')
  })

  it('fills in the code from an invitation link but waits for the email', async () => {
    vi.mocked(api).mockResolvedValue({ session_id: 's1', access_token: 'tok', status: 'in_progress' })
    const wrapper = await renderStart('/?t=ABCD-EFGH')
    await flushPromises()
    expect((wrapper.get('#invitation').element as HTMLInputElement).value).toBe('ABCD-EFGH')
    expect(vi.mocked(api)).not.toHaveBeenCalled() // nothing is sent until they press Continue

    await wrapper.get('#email').setValue('  Ada@Example.org ')
    await wrapper.get('form').trigger('submit')
    await flushPromises()
    expect(wrapper.text()).toContain('test page')
    const sent = (vi.mocked(api).mock.calls[0][1] as { body: { token: string; email?: string } }).body
    expect(sent).toEqual({ token: 'ABCDEFGH', email: 'Ada@Example.org' }) // the server lower-cases it
  })

  it('sends no email at all when none is typed, for an invitation made without one', async () => {
    vi.mocked(api).mockResolvedValue({ session_id: 's1', access_token: 'tok', status: 'created' })
    const wrapper = await renderStart()
    await submit(wrapper, 'abcd-efgh')
    const sent = (vi.mocked(api).mock.calls[0][1] as { body: Record<string, unknown> }).body
    expect('email' in sent && sent.email !== undefined).toBe(false)
  })

  describe('passwords', () => {
    const sentBody = (call = 0) => (vi.mocked(api).mock.calls[call][1] as { body: Record<string, unknown> }).body
    const fill = async (w: Awaited<ReturnType<typeof renderStart>>, ids: Record<string, string>) => {
      for (const [id, value] of Object.entries(ids)) await w.get(`#${id}`).setValue(value)
    }

    it('asks the candidate to choose a password when the server says it is their first time', async () => {
      vi.mocked(api).mockRejectedValueOnce(new ApiError(409, 'password_needed', {}))
      const wrapper = await renderStart('/?t=ABCD-EFGH')
      await fill(wrapper, { email: 'ada@example.org' })
      await wrapper.get('form').trigger('submit')
      await flushPromises()

      // not an error: the code and email were right, so the page moves on to choosing a password
      expect(wrapper.find('[role=alert]').exists()).toBe(false)
      expect(wrapper.text()).toContain('Now choose a password')
      expect(wrapper.find('#new-password').exists()).toBe(true)
      expect(wrapper.find('#password').exists()).toBe(false)
      expect(wrapper.get('button[type=submit]').text()).toBe('Create password and continue')
      expect(sentBody(0)).toEqual({ token: 'ABCDEFGH', email: 'ada@example.org' })
    })

    it('checks the new password in the page, then sends it as new_password', async () => {
      vi.mocked(api).mockRejectedValueOnce(new ApiError(409, 'password_needed', {}))
      vi.mocked(api).mockResolvedValueOnce({ session_id: 's1', access_token: 'tok', status: 'created' })
      const wrapper = await renderStart('/?t=ABCD-EFGH')
      await fill(wrapper, { email: 'ada@example.org' })
      await wrapper.get('form').trigger('submit')
      await flushPromises()

      await fill(wrapper, { 'new-password': 'short', 'repeat-password': 'short' })
      await wrapper.get('form').trigger('submit')
      await flushPromises()
      expect(wrapper.get('[role=alert]').text()).toContain('at least 8 characters')

      await fill(wrapper, { 'new-password': 'a long enough one', 'repeat-password': 'a long enough two' })
      await wrapper.get('form').trigger('submit')
      await flushPromises()
      expect(wrapper.get('[role=alert]').text()).toContain('not the same')
      expect(vi.mocked(api)).toHaveBeenCalledTimes(1) // neither mistake went to the server

      await fill(wrapper, { 'repeat-password': 'a long enough one' })
      await wrapper.get('form').trigger('submit')
      await flushPromises()
      expect(sentBody(1)).toEqual({
        token: 'ABCDEFGH',
        email: 'ada@example.org',
        new_password: 'a long enough one',
      })
      expect(wrapper.text()).toContain('precheck page')
    })

    it('signs in with email and password and no code', async () => {
      vi.mocked(api).mockResolvedValue({ session_id: 's1', access_token: 'tok', status: 'in_progress' })
      const wrapper = await renderStart()
      expect((wrapper.get('button[type=submit]').element as HTMLButtonElement).disabled).toBe(true)
      await fill(wrapper, { email: ' ada@example.org ', password: 'her password' })
      expect((wrapper.get('button[type=submit]').element as HTMLButtonElement).disabled).toBe(false)
      await wrapper.get('form').trigger('submit')
      await flushPromises()

      expect(sentBody()).toEqual({ email: 'ada@example.org', password: 'her password' })
      expect(wrapper.text()).toContain('test page')
    })

    it('keeps the password hidden until asked, and says what to do if it is forgotten', async () => {
      const wrapper = await renderStart()
      expect(wrapper.get('#password').attributes('type')).toBe('password')
      await wrapper.get('input[type=checkbox]').setValue(true)
      expect(wrapper.get('#password').attributes('type')).toBe('text')
      expect(wrapper.text()).toContain('Ask the person who invited you to send you a new link')
    })

    it('says a test is open on another device, and how to carry on', async () => {
      vi.mocked(api).mockRejectedValue(new ApiError(409, 'test_open_elsewhere', { retry_after_s: 40 }))
      const wrapper = await renderStart()
      await fill(wrapper, { email: 'ada@example.org', password: 'her password' })
      await wrapper.get('form').trigger('submit')
      await flushPromises()
      expect(wrapper.get('[role=alert]').text()).toContain('open on another device')
      expect(wrapper.get('[role=alert]').text()).toContain('wait a minute')
    })
  })

  it('sends a finished candidate to the end of the flow', async () => {
    vi.mocked(api).mockResolvedValue({ session_id: 's1', access_token: 'tok', status: 'finished' })
    const wrapper = await renderStart()
    await submit(wrapper, 'ABCD-EFGH')
    expect(wrapper.text()).toContain('done page')
  })

  it('does not let the button be pressed with an empty code', async () => {
    const wrapper = await renderStart()
    expect((wrapper.get('button[type=submit]').element as HTMLButtonElement).disabled).toBe(true)
    await wrapper.get('#invitation').setValue('ABCD')
    expect((wrapper.get('button[type=submit]').element as HTMLButtonElement).disabled).toBe(false)
  })

  it('says plainly when the code is wrong, and what to do next', async () => {
    vi.mocked(api).mockRejectedValue(new ApiError(401, 'invalid_invitation', {}))
    const wrapper = await renderStart()
    await submit(wrapper, 'ZZZZ-ZZZZ')
    expect(wrapper.get('[role=alert]').text()).toContain('code, email or password does not match an invitation')
    expect(wrapper.text()).toContain(HELP_CONTACT)
  })

  it('says when an early test opens, and that the same code will work then', async () => {
    vi.mocked(api).mockRejectedValue(
      new ApiError(403, 'sitting_not_open_yet', { opens_at: '2026-10-24T12:07:00+00:00' }),
    )
    const wrapper = await renderStart()
    await submit(wrapper, 'ABCD-EFGH')
    const shown = wrapper.get('[role=alert]').text()
    expect(shown).toContain('has not opened yet')
    // in the reader's own time zone, so only the shape is fixed
    expect(shown).toMatch(/It opens on [A-Za-z]+ \d+ October at \d\d:\d\d\./)
    expect(shown).toContain('same code')
    // early is not closed: nothing is offered to resume
    expect(vi.mocked(api).mock.calls.map((call) => call[0])).toEqual(['/api/session/start'])
  })

  it('says a closed test is closed, without telling the candidate to come back', async () => {
    vi.mocked(api).mockRejectedValue(new ApiError(403, 'no_open_sitting', {}))
    const wrapper = await renderStart()
    await submit(wrapper, 'ABCD-EFGH')
    const shown = wrapper.get('[role=alert]').text()
    expect(shown).toContain('not open right now')
    expect(shown).toContain('may have closed')
    expect(shown).not.toContain('come back')
  })

  describe('once the sitting has closed', () => {
    const closed = new ApiError(409, 'no_open_sitting', {})
    const resumed = { session_id: 's9', access_token: 'upload-token', status: 'finished', expires_at: 'x' }

    it('finishes the upload of a test already taken, using the same code', async () => {
      vi.mocked(api).mockImplementation((async (path: string) => {
        if (path === '/api/session/start') throw closed
        return resumed
      }) as unknown as typeof api)
      const wrapper = await renderStart()
      await submit(wrapper, 'abcd-efgh')

      expect(vi.mocked(api).mock.calls.map((call) => call[0])).toEqual([
        '/api/session/start',
        '/api/session/resume',
      ])
      expect((vi.mocked(api).mock.calls[1][1] as { body: { token: string } }).body.token).toBe('ABCDEFGH')
      expect(getSessionId()).toBe('s9')
      expect(wrapper.text()).toContain('uploading page')
    })

    it('keeps saying the test is not open when there is nothing to finish', async () => {
      vi.mocked(api).mockImplementation((async (path: string) => {
        throw path === '/api/session/start' ? closed : new ApiError(409, 'nothing_to_resume', {})
      }) as unknown as typeof api)
      const wrapper = await renderStart()
      await submit(wrapper, 'ABCD-EFGH')

      expect(wrapper.get('[role=alert]').text()).toContain('not open right now')
      expect(getSessionId()).toBeNull()
    })

    it('does not try to resume for any other refusal', async () => {
      vi.mocked(api).mockRejectedValue(new ApiError(401, 'invalid_invitation', {}))
      const wrapper = await renderStart()
      await submit(wrapper, 'WRONG')
      expect(vi.mocked(api)).toHaveBeenCalledTimes(1)
    })
  })

  it('tells a throttled candidate how long to wait', async () => {
    vi.mocked(api).mockRejectedValue(new ApiError(429, 'too_many_attempts', { retry_after_s: 120 }))
    const wrapper = await renderStart()
    await submit(wrapper, 'ZZZZ-ZZZZ')
    expect(wrapper.get('[role=alert]').text()).toContain('wait about 2 minutes')
  })

  it('falls back to a plain message for anything unexpected', async () => {
    vi.mocked(api).mockRejectedValue(new Error('network'))
    const wrapper = await renderStart()
    await submit(wrapper, 'ABCD-EFGH')
    expect(wrapper.get('[role=alert]').text()).toContain('Something went wrong. Please try again.')
    expect(wrapper.text()).toContain(HELP_CONTACT)
  })

  it('lets the candidate try again after an error', async () => {
    vi.mocked(api).mockRejectedValueOnce(new Error('network'))
    const wrapper = await renderStart()
    await submit(wrapper, 'ABCD-EFGH')
    expect((wrapper.get('button[type=submit]').element as HTMLButtonElement).disabled).toBe(false)
  })
})
