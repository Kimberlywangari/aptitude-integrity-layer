import { act, cleanup, render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import UploadStatus from '../src/candidate/UploadStatus'
import { UPLOAD_DONE, UPLOAD_STUCK } from '../src/candidate/copy'
import { api } from '../src/lib/api'
import { resetMock, setMockLatency } from '../src/lib/mock'
import { clearSession, saveSession } from '../src/lib/session'

vi.mock('../src/lib/api', async (importOriginal) =>
  (await import('./helpers/mockedApi')).withMockedApi(await importOriginal()),
)

const settle = (ms: number) => act(async () => void (await vi.advanceTimersByTimeAsync(ms)))
const hasButton = (name: string) => screen.queryByRole('button', { name }) !== null

function renderPage() {
  return render(
    <MemoryRouter>
      <UploadStatus />
    </MemoryRouter>,
  )
}

describe('UploadStatus', () => {
  beforeEach(() => {
    vi.useFakeTimers()
    setMockLatency(0)
    resetMock()
    saveSession('s1', 'tok')
  })

  afterEach(() => {
    cleanup()
    clearSession()
    vi.useRealTimers()
    vi.mocked(api).mockReset()
  })

  it('shows progress, then offers Finish once everything is uploaded', async () => {
    renderPage()
    await settle(0)
    expect(screen.getByText(/Uploaded 9 of 42 parts/)).toBeTruthy()
    expect(hasButton('Finish')).toBe(false)

    await settle(3000 * 4) // four more polls take the mock manifest to 42 of 42
    expect(screen.getByText(UPLOAD_DONE)).toBeTruthy()
    expect(hasButton('Finish')).toBe(true)
    expect(hasButton('Quit anyway')).toBe(false)
  })

  it('stops polling once the upload is complete', async () => {
    renderPage()
    await settle(3000 * 6)
    const calls = vi.mocked(api).mock.calls.length
    await settle(3000 * 5)
    expect(vi.mocked(api).mock.calls.length).toBe(calls)
  })

  it('offers Quit anyway after repeated failures, never before', async () => {
    vi.mocked(api).mockRejectedValue(new Error('offline'))
    renderPage()
    await settle(0)
    expect(hasButton('Quit anyway')).toBe(false)

    await settle(3000 * 3)
    expect(screen.getByText(UPLOAD_STUCK)).toBeTruthy()
    expect(hasButton('Quit anyway')).toBe(true)
    expect(hasButton('Finish')).toBe(false)
  })
})
