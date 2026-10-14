import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import Start from '../src/candidate/Start'
import { api, ApiError } from '../src/lib/api'
import { clearSession, getSessionId } from '../src/lib/session'

vi.mock('../src/lib/api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../src/lib/api')>()
  return { ...actual, api: vi.fn() }
})

function renderStart(entry = '/') {
  return render(
    <MemoryRouter initialEntries={[entry]}>
      <Routes>
        <Route path="/" element={<Start />} />
        <Route path="/precheck" element={<p>precheck page</p>} />
        <Route path="/test" element={<p>test page</p>} />
        <Route path="/done" element={<p>done page</p>} />
      </Routes>
    </MemoryRouter>,
  )
}

const submit = (code: string) => {
  fireEvent.change(screen.getByLabelText('Invitation code'), { target: { value: code } })
  fireEvent.click(screen.getByRole('button', { name: 'Continue' }))
}

describe('Start', () => {
  beforeEach(() => {
    clearSession()
    vi.mocked(api).mockReset()
  })

  afterEach(() => {
    cleanup()
    clearSession()
  })

  it('sends a typed code in its canonical form and goes to the device check', async () => {
    vi.mocked(api).mockResolvedValue({ session_id: 's1', access_token: 'tok', status: 'created' })
    renderStart()
    submit('abcd-efgh')

    expect(await screen.findByText('precheck page')).toBeTruthy()
    const [path, options] = vi.mocked(api).mock.calls[0] as [string, { body: { token: string } }]
    expect(path).toBe('/api/session/start')
    expect(options.body.token).toBe('ABCDEFGH')
    expect(getSessionId()).toBe('s1')
  })

  it('reads O and I as 0 and 1', async () => {
    vi.mocked(api).mockResolvedValue({ session_id: 's1', access_token: 'tok', status: 'created' })
    renderStart()
    submit('OO11-ABCD')
    await waitFor(() => expect(api).toHaveBeenCalled())
    const options = vi.mocked(api).mock.calls[0][1] as { body: { token: string } }
    expect(options.body.token).toBe('0011ABCD')
  })

  it('leaves a long token from the first seed as it was', async () => {
    vi.mocked(api).mockResolvedValue({ session_id: 's1', access_token: 'tok', status: 'created' })
    renderStart()
    submit('a3f9c1d2e4b5a6f7c8d9e0f1')
    await waitFor(() => expect(api).toHaveBeenCalled())
    const options = vi.mocked(api).mock.calls[0][1] as { body: { token: string } }
    expect(options.body.token).toBe('a3f9c1d2e4b5a6f7c8d9e0f1')
  })

  it('starts by itself from an invitation link', async () => {
    vi.mocked(api).mockResolvedValue({ session_id: 's1', access_token: 'tok', status: 'in_progress' })
    renderStart('/?t=ABCD-EFGH')
    expect(await screen.findByText('test page')).toBeTruthy()
    const options = vi.mocked(api).mock.calls[0][1] as { body: { token: string } }
    expect(options.body.token).toBe('ABCDEFGH')
  })

  it('says plainly when the code is wrong', async () => {
    vi.mocked(api).mockRejectedValue(new ApiError(401, 'invalid_invitation', {}))
    renderStart()
    submit('ZZZZ-ZZZZ')
    expect((await screen.findByRole('alert')).textContent).toContain('not valid')
  })

  it('tells a throttled candidate to wait', async () => {
    vi.mocked(api).mockRejectedValue(new ApiError(429, 'too_many_attempts', { retry_after_s: 120 }))
    renderStart()
    submit('ZZZZ-ZZZZ')
    expect((await screen.findByRole('alert')).textContent).toContain('wait a few minutes')
  })
})
