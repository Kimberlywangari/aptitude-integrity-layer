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

  it('starts by itself from an invitation link', async () => {
    vi.mocked(api).mockResolvedValue({ session_id: 's1', access_token: 'tok', status: 'in_progress' })
    const wrapper = await renderStart('/?t=ABCD-EFGH')
    await flushPromises()
    expect(wrapper.text()).toContain('test page')
    expect(sentToken()).toBe('ABCDEFGH')
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
    expect(wrapper.get('[role=alert]').text()).toContain('not valid')
    expect(wrapper.text()).toContain(HELP_CONTACT)
  })

  it('says when the test is not open yet', async () => {
    vi.mocked(api).mockRejectedValue(new ApiError(409, 'no_open_sitting', {}))
    const wrapper = await renderStart()
    await submit(wrapper, 'ABCD-EFGH')
    expect(wrapper.get('[role=alert]').text()).toContain('not open right now')
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
