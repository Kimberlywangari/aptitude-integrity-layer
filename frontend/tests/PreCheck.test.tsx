import { act, cleanup, fireEvent, render, screen } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import PreCheck from '../src/candidate/PreCheck'
import { DEVICE_ERRORS, MIC_MUTED_MESSAGE, MIC_QUIET_MESSAGE } from '../src/candidate/copy'
import { api } from '../src/lib/api'
import { acquireDevices } from '../src/lib/devices'
import type { DeviceHandle } from '../src/lib/devices'
import { resetMock, setMockLatency } from '../src/lib/mock'
import { clearSession, saveSession } from '../src/lib/session'

vi.mock('../src/lib/api', async (importOriginal) =>
  (await import('./helpers/mockedApi')).withMockedApi(await importOriginal()),
)
vi.mock('../src/lib/devices', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../src/lib/devices')>()
  return { ...actual, acquireDevices: vi.fn() }
})

const LOUD = 0.05
const QUIET = 0.0001

interface Fake {
  handle: DeviceHandle
  setLevel(rms: number): void
  setMuted(muted: boolean): void
  stop: ReturnType<typeof vi.fn>
}

function fakeDevices(): Fake {
  let rms = LOUD
  let muted = false
  const stop = vi.fn()
  const handle: DeviceHandle = {
    stream: { getVideoTracks: () => [{ readyState: 'live' }] } as unknown as MediaStream,
    cameraLabel: 'Integrated Camera',
    micLabel: 'Headset Microphone',
    videoSize: { width: 320, height: 240 },
    micMuted: () => muted,
    readMicLevel: () => ({ rms, peak: rms * 4 }),
    stop,
  }
  return {
    handle,
    stop,
    setLevel: (value) => {
      rms = value
    },
    setMuted: (value) => {
      muted = value
    },
  }
}

function renderPage() {
  return render(
    <MemoryRouter initialEntries={['/precheck']}>
      <Routes>
        <Route path="/precheck" element={<PreCheck />} />
        <Route path="/integrity" element={<p>integrity page</p>} />
        <Route path="/" element={<p>start page</p>} />
      </Routes>
    </MemoryRouter>,
  )
}

const settle = (ms = 0) => act(async () => void (await vi.advanceTimersByTimeAsync(ms)))
const button = (name: RegExp | string) => screen.getByRole('button', { name }) as HTMLButtonElement

async function startChecks() {
  fireEvent.click(screen.getByLabelText(/I understand/))
  fireEvent.click(button('Check my camera and microphone'))
  await settle()
}

describe('PreCheck', () => {
  beforeEach(() => {
    vi.useFakeTimers()
    setMockLatency(0)
    resetMock()
    saveSession('s1', 'tok')
    vi.mocked(api).mockClear()
  })

  afterEach(() => {
    cleanup()
    clearSession()
    vi.useRealTimers()
    vi.mocked(acquireDevices).mockReset()
  })

  it('goes back to the start page when there is no session', async () => {
    clearSession()
    renderPage()
    await settle()
    expect(screen.getByText('start page')).toBeTruthy()
  })

  it('cannot start the checks before the notice is accepted', () => {
    renderPage()
    expect(button('Check my camera and microphone').disabled).toBe(true)
    expect(button('Continue to the test').disabled).toBe(true)
  })

  it('passes with a working camera and a voice, reports it, and moves on', async () => {
    const fake = fakeDevices()
    vi.mocked(acquireDevices).mockResolvedValue(fake.handle)
    renderPage()
    await startChecks()

    expect(screen.getByText('Camera working.')).toBeTruthy()
    expect(button('Continue to the test').disabled).toBe(true) // microphone not heard yet

    await settle(1200)
    expect(screen.getByText('Microphone working.')).toBeTruthy()
    expect(button('Continue to the test').disabled).toBe(false)

    fireEvent.click(button('Continue to the test'))
    await settle()

    expect(screen.getByText('integrity page')).toBeTruthy()
    expect(fake.stop).toHaveBeenCalled()
    const [path, options] = vi.mocked(api).mock.calls[0] as [string, { body: Record<string, unknown> }]
    expect(path).toBe('/api/precheck/result')
    expect(options.body).toMatchObject({
      camera_ok: true,
      mic_ok: true,
      device_labels: { camera: 'Integrated Camera', mic: 'Headset Microphone' },
      video_size: { width: 320, height: 240 },
    })
  })

  it('explains a blocked camera and keeps Continue disabled', async () => {
    vi.mocked(acquireDevices).mockRejectedValue(new DOMException('no', 'NotAllowedError'))
    renderPage()
    await startChecks()
    expect(screen.getByRole('alert').textContent).toBe(DEVICE_ERRORS.denied)
    expect(button('Continue to the test').disabled).toBe(true)
  })

  it('tells apart a missing device from one in use', async () => {
    vi.mocked(acquireDevices).mockRejectedValueOnce(new DOMException('no', 'NotFoundError'))
    renderPage()
    await startChecks()
    expect(screen.getByRole('alert').textContent).toBe(DEVICE_ERRORS.not_found)

    vi.mocked(acquireDevices).mockRejectedValueOnce(new DOMException('no', 'NotReadableError'))
    fireEvent.click(button('Check my camera and microphone'))
    await settle()
    expect(screen.getByRole('alert').textContent).toBe(DEVICE_ERRORS.in_use)
  })

  it('fails a muted microphone with guidance and lets the candidate retry', async () => {
    const fake = fakeDevices()
    fake.setMuted(true)
    vi.mocked(acquireDevices).mockResolvedValue(fake.handle)
    renderPage()
    await startChecks()

    await settle(10_500)
    expect(screen.getAllByText(MIC_MUTED_MESSAGE).length).toBeGreaterThan(0)
    expect(button('Continue to the test').disabled).toBe(true)

    fake.setMuted(false)
    fireEvent.click(button('Try the microphone again'))
    await settle(1200)
    expect(screen.getByText('Microphone working.')).toBeTruthy()
    expect(button('Continue to the test').disabled).toBe(false)
  })

  it('asks the candidate to speak up when nothing was heard', async () => {
    const fake = fakeDevices()
    fake.setLevel(QUIET)
    vi.mocked(acquireDevices).mockResolvedValue(fake.handle)
    renderPage()
    await startChecks()
    await settle(10_500)
    expect(screen.getByText(MIC_QUIET_MESSAGE)).toBeTruthy()
  })

  it('releases the camera when the candidate leaves the page', async () => {
    const fake = fakeDevices()
    vi.mocked(acquireDevices).mockResolvedValue(fake.handle)
    const { unmount } = renderPage()
    await startChecks()
    unmount()
    expect(fake.stop).toHaveBeenCalled()
  })
})
