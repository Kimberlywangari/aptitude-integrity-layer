import type { VueWrapper } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import PreCheck from '../src/candidate/PreCheck.vue'
import {
  CAPTURE_PROBLEMS,
  DEVICE_ERRORS,
  FULLSCREEN_UNSUPPORTED,
  MIC_CHECK_OFF_NOTE,
  MIC_MUTED_MESSAGE,
  MIC_QUIET_MESSAGE,
  NOTIFICATIONS_CHECKBOX,
  UNSUPPORTED_BROWSER,
} from '../src/candidate/copy'
import { api } from '../src/lib/api'
import { captureProblem } from '../src/lib/browser'
import { acquireDevices } from '../src/lib/devices'
import type { DeviceHandle } from '../src/lib/devices'
import { resetMock, setMockLatency } from '../src/lib/mock'
import { clearSession, saveSession } from '../src/lib/session'
import { fs, resetFullscreen } from './helpers/fakeFullscreen'
import { mountPage, settle } from './helpers/render'

vi.mock('../src/lib/api', async (importOriginal) =>
  (await import('./helpers/mockedApi')).withMockedApi(await importOriginal()),
)
vi.mock('../src/lib/devices', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../src/lib/devices')>()
  return { ...actual, acquireDevices: vi.fn() }
})
vi.mock('../src/lib/fullscreen', async () => (await import('./helpers/fakeFullscreen')).fullscreenModule)
vi.mock('../src/lib/browser', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../src/lib/browser')>()
  return { ...actual, captureProblem: vi.fn(() => null) }
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

type Page = VueWrapper

const advance = (ms: number) => vi.advanceTimersByTimeAsync(ms)
const wait = (ms = 0) => settle(advance, ms)

async function renderPage(): Promise<Page> {
  const { wrapper } = await mountPage('/precheck', {
    '/precheck': PreCheck,
    '/integrity': 'integrity page',
    '/candidate': 'start page',
  })
  await wait()
  return wrapper
}

const button = (w: Page, name: string) => {
  const found = w.findAll('button').find((b) => b.text().trim() === name)
  if (!found) throw new Error(`no button "${name}" in: ${w.findAll('button').map((b) => b.text().trim())}`)
  return found
}
const isDisabled = (w: Page, name: string) => (button(w, name).element as HTMLButtonElement).disabled
const hasButton = (w: Page, name: string) => w.findAll('button').some((b) => b.text().trim() === name)

async function press(w: Page, name: string) {
  await button(w, name).trigger('click')
  await wait()
}

const tick = (w: Page) => w.get('.check input').setValue(true)

async function toPermissions(w: Page) {
  await tick(w) // "I understand"
  await press(w, 'Continue')
  await tick(w) // "I have turned off notifications"
  await press(w, 'Continue')
}

async function toDevices(w: Page) {
  await toPermissions(w)
  await press(w, 'Allow camera and microphone')
}

async function toReady(w: Page) {
  await toDevices(w)
  await wait(1200) // heard the voice
  await press(w, 'Continue')
  await press(w, 'Go full screen')
  await press(w, 'Continue')
}

describe('PreCheck', () => {
  beforeEach(() => {
    vi.useFakeTimers()
    setMockLatency(0)
    resetMock()
    resetFullscreen()
    saveSession('s1', 'tok')
    vi.mocked(api).mockClear()
    vi.mocked(captureProblem).mockReturnValue(null)
  })

  afterEach(() => {
    document.body.innerHTML = ''
    clearSession()
    vi.useRealTimers()
    vi.unstubAllEnvs()
    vi.mocked(acquireDevices).mockReset()
  })

  it('goes back to the start page when there is no session', async () => {
    clearSession()
    const w = await renderPage()
    expect(w.text()).toContain('start page')
  })

  describe('step 1: before you start', () => {
    it('cannot go on until the notice is accepted', async () => {
      const w = await renderPage()
      expect(isDisabled(w, 'Continue')).toBe(true)
      await tick(w)
      expect(isDisabled(w, 'Continue')).toBe(false)
    })

    it('warns, without blocking, about a browser that has not been tested', async () => {
      const w = await renderPage()
      // jsdom's user agent is not Chrome or Edge on a desktop
      expect(w.text()).toContain(UNSUPPORTED_BROWSER)
      await tick(w)
      expect(isDisabled(w, 'Continue')).toBe(false)
    })

    it.each(['insecure', 'no_media'] as const)('blocks when the camera cannot be asked for (%s)', async (why) => {
      vi.mocked(captureProblem).mockReturnValue(why)
      const w = await renderPage()
      await tick(w)
      expect(w.get('[role=alert]').text()).toBe(CAPTURE_PROBLEMS[why])
      expect(isDisabled(w, 'Continue')).toBe(true)
    })
  })

  describe('step 2: notifications', () => {
    it('asks the candidate to turn them off, and will not go on without the confirmation', async () => {
      const w = await renderPage()
      await tick(w)
      await press(w, 'Continue')

      expect(w.text()).toContain('Turn off notifications')
      expect(w.text()).toContain(NOTIFICATIONS_CHECKBOX)
      expect(w.text()).toContain('Focus assist')
      expect(isDisabled(w, 'Continue')).toBe(true)

      await tick(w)
      expect(isDisabled(w, 'Continue')).toBe(false)
    })

    it('lets the candidate go back a step', async () => {
      const w = await renderPage()
      await tick(w)
      await press(w, 'Continue')
      await press(w, 'Back')
      expect(w.text()).toContain('I understand')
    })
  })

  describe('step 3: camera and microphone permission', () => {
    it('asks for both in one go and moves on when they are allowed', async () => {
      const fake = fakeDevices()
      vi.mocked(acquireDevices).mockResolvedValue(fake.handle)
      const w = await renderPage()
      await toPermissions(w)

      expect(w.text()).toContain('Your browser will ask once')
      await press(w, 'Allow camera and microphone')
      expect(acquireDevices).toHaveBeenCalledOnce()
      expect(w.text()).toContain('Camera working')
    })

    it('explains a blocked camera, says how to unblock it, and offers another try', async () => {
      vi.mocked(acquireDevices).mockRejectedValue(new DOMException('no', 'NotAllowedError'))
      const w = await renderPage()
      await toDevices(w)

      const alert = w.get('[role=alert]')
      expect(alert.text()).toContain(DEVICE_ERRORS.denied)
      expect(alert.text()).toContain('lock icon')
      expect(hasButton(w, 'Try again')).toBe(true)
      expect(hasButton(w, 'Continue')).toBe(false) // still on the permission step
    })

    it('tells apart a missing device from one in use', async () => {
      vi.mocked(acquireDevices).mockRejectedValueOnce(new DOMException('no', 'NotFoundError'))
      const w = await renderPage()
      await toDevices(w)
      expect(w.get('[role=alert]').text()).toBe(DEVICE_ERRORS.not_found)

      vi.mocked(acquireDevices).mockRejectedValueOnce(new DOMException('no', 'NotReadableError'))
      await press(w, 'Try again')
      expect(w.get('[role=alert]').text()).toBe(DEVICE_ERRORS.in_use)
    })

    it('recovers when the retry works', async () => {
      const fake = fakeDevices()
      vi.mocked(acquireDevices).mockRejectedValueOnce(new DOMException('no', 'NotAllowedError'))
      vi.mocked(acquireDevices).mockResolvedValueOnce(fake.handle)
      const w = await renderPage()
      await toDevices(w)
      await press(w, 'Try again')
      expect(w.text()).toContain('Camera working')
    })
  })

  describe('step 4: checking the devices', () => {
    it('needs a voice before the candidate can continue', async () => {
      const fake = fakeDevices()
      vi.mocked(acquireDevices).mockResolvedValue(fake.handle)
      const w = await renderPage()
      await toDevices(w)

      expect(w.text()).toContain('Camera working')
      expect(isDisabled(w, 'Continue')).toBe(true) // microphone not heard yet

      await wait(1200)
      expect(w.text()).toContain('Microphone working.')
      expect(isDisabled(w, 'Continue')).toBe(false)
    })

    it('fails a muted microphone with guidance and lets the candidate retry', async () => {
      const fake = fakeDevices()
      fake.setMuted(true)
      vi.mocked(acquireDevices).mockResolvedValue(fake.handle)
      const w = await renderPage()
      await toDevices(w)

      await wait(10_500)
      expect(w.text()).toContain(MIC_MUTED_MESSAGE)
      expect(isDisabled(w, 'Continue')).toBe(true)

      fake.setMuted(false)
      await press(w, 'Try the microphone again')
      await wait(1200)
      expect(w.text()).toContain('Microphone working.')
      expect(isDisabled(w, 'Continue')).toBe(false)
    })

    it('asks the candidate to speak up when nothing was heard', async () => {
      const fake = fakeDevices()
      fake.setLevel(QUIET)
      vi.mocked(acquireDevices).mockResolvedValue(fake.handle)
      const w = await renderPage()
      await toDevices(w)
      await wait(10_500)
      expect(w.text()).toContain(MIC_QUIET_MESSAGE)
    })

    it('releases the camera when the candidate leaves the page', async () => {
      const fake = fakeDevices()
      vi.mocked(acquireDevices).mockResolvedValue(fake.handle)
      const w = await renderPage()
      await toDevices(w)
      w.unmount()
      expect(fake.stop).toHaveBeenCalled()
    })
  })

  describe('step 5: full screen', () => {
    it('asks for it with a button press, and goes on once the browser agrees', async () => {
      const fake = fakeDevices()
      vi.mocked(acquireDevices).mockResolvedValue(fake.handle)
      const w = await renderPage()
      await toDevices(w)
      await wait(1200)
      await press(w, 'Continue')

      expect(w.text()).toContain('The test runs full screen')
      expect(hasButton(w, 'Continue')).toBe(false) // nothing to continue with until it is on
      await press(w, 'Go full screen')
      expect(fs.active).toBe(true)
      expect(hasButton(w, 'Continue')).toBe(true)
    })

    it('says so when the browser cannot do full screen, and does not let the candidate pass', async () => {
      fs.supported = false
      const fake = fakeDevices()
      vi.mocked(acquireDevices).mockResolvedValue(fake.handle)
      const w = await renderPage()
      await toDevices(w)
      await wait(1200)
      await press(w, 'Continue')

      expect(w.get('[role=alert]').text()).toBe(FULLSCREEN_UNSUPPORTED)
      expect(isDisabled(w, 'Go full screen')).toBe(true)
    })
  })

  describe('the last step', () => {
    it('reports everything, releases the camera and moves on', async () => {
      const fake = fakeDevices()
      vi.mocked(acquireDevices).mockResolvedValue(fake.handle)
      const w = await renderPage()
      await toReady(w)

      expect(w.text()).toContain('Everything the test needs is in place.')
      await press(w, 'Continue to the test')

      expect(w.text()).toContain('integrity page')
      expect(fake.stop).toHaveBeenCalled()
      const [path, options] = vi.mocked(api).mock.calls[0] as [string, { body: Record<string, unknown> }]
      expect(path).toBe('/api/precheck/result')
      expect(options.body).toMatchObject({
        camera_ok: true,
        mic_ok: true,
        mic_checked: true,
        notifications_off_confirmed: true,
        fullscreen_ok: true,
        device_labels: { camera: 'Integrated Camera', mic: 'Headset Microphone' },
        video_size: { width: 320, height: 240 },
        browser: { name: expect.any(String), version: expect.any(String) },
      })
    })
  })

  describe('with the microphone check switched off (VITE_MIC_CHECK=off)', () => {
    beforeEach(() => {
      vi.stubEnv('VITE_MIC_CHECK', 'off')
    })

    it('needs only the camera, and reports the microphone as not checked', async () => {
      const fake = fakeDevices()
      fake.setLevel(QUIET) // a silent microphone must not block anyone
      vi.mocked(acquireDevices).mockResolvedValue(fake.handle)
      const w = await renderPage()
      await toDevices(w)

      expect(w.text()).toContain('Camera working')
      expect(w.text()).toContain(MIC_CHECK_OFF_NOTE)
      expect(w.find('[role=meter]').exists()).toBe(false)
      expect(isDisabled(w, 'Continue')).toBe(false)

      await press(w, 'Continue')
      await press(w, 'Go full screen')
      await press(w, 'Continue')
      await press(w, 'Continue to the test')

      expect(w.text()).toContain('integrity page')
      const [, options] = vi.mocked(api).mock.calls[0] as [string, { body: Record<string, unknown> }]
      expect(options.body).toMatchObject({ camera_ok: true, mic_ok: false, mic_checked: false, mic_peak: 0 })
    })

    it('still asks for the microphone permission, because the exam records it', async () => {
      const fake = fakeDevices()
      vi.mocked(acquireDevices).mockResolvedValue(fake.handle)
      const w = await renderPage()
      await toPermissions(w)
      expect(hasButton(w, 'Allow camera and microphone')).toBe(true)
    })

    it('still needs the camera', async () => {
      vi.mocked(acquireDevices).mockRejectedValue(new DOMException('no', 'NotAllowedError'))
      const w = await renderPage()
      await toDevices(w)
      expect(w.get('[role=alert]').text()).toContain(DEVICE_ERRORS.denied)
      expect(hasButton(w, 'Continue')).toBe(false)
    })
  })

  describe('with full screen switched off (VITE_FULLSCREEN=off)', () => {
    it('leaves the step out and still reports the result', async () => {
      vi.stubEnv('VITE_FULLSCREEN', 'off')
      const fake = fakeDevices()
      vi.mocked(acquireDevices).mockResolvedValue(fake.handle)
      const w = await renderPage()
      await toDevices(w)
      await wait(1200)
      await press(w, 'Continue') // straight to the last step
      expect(w.text()).toContain('Everything the test needs is in place.')
      expect(w.text()).not.toContain('Go full screen')

      await press(w, 'Continue to the test')
      const [, options] = vi.mocked(api).mock.calls[0] as [string, { body: Record<string, unknown> }]
      expect(options.body).toMatchObject({ fullscreen_ok: true })
    })
  })
})
