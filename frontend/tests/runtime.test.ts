import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { startActionLogger } from '../src/lib/actionLogger'
import { acquireDevices } from '../src/lib/devices'
import { flushEvents, startEventLog } from '../src/lib/eventLog'
import { startHeartbeat } from '../src/lib/heartbeat'
import { holdDevices, releaseDevices } from '../src/lib/media'
import { startMicWatch } from '../src/lib/micWatch'
import {
  RecorderUnsupportedError,
  ensureRecording,
  recordingState,
  startRecording,
} from '../src/lib/recording'
import type { RecordingState } from '../src/lib/recording'
import { FIRST_UPLOAD_WAIT_MS, endTestRuntime, prepareRecording, startTestRuntime } from '../src/lib/runtime'
import { startUploader, waitForUploads } from '../src/lib/uploader'
import { fakeDevices } from './helpers/fakeMedia'

vi.mock('../src/lib/devices', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../src/lib/devices')>()),
  acquireDevices: vi.fn(),
}))
vi.mock('../src/lib/eventLog', () => ({ startEventLog: vi.fn(), flushEvents: vi.fn(async () => true) }))
vi.mock('../src/lib/actionLogger', () => ({ startActionLogger: vi.fn() }))
vi.mock('../src/lib/heartbeat', () => ({ startHeartbeat: vi.fn() }))
vi.mock('../src/lib/micWatch', () => ({ startMicWatch: vi.fn() }))
vi.mock('../src/lib/uploader', () => ({ startUploader: vi.fn(), waitForUploads: vi.fn() }))
vi.mock('../src/lib/recording', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../src/lib/recording')>()),
  ensureRecording: vi.fn(async () => undefined),
  recordingState: vi.fn((): RecordingState => 'off'),
  startRecording: vi.fn(async () => undefined),
}))

describe('prepareRecording()', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    vi.mocked(recordingState).mockReturnValue('off')
    vi.mocked(waitForUploads).mockResolvedValue(true)
    releaseDevices()
  })
  afterEach(() => releaseDevices())

  it('starts the log, records on the stream the pre-check handed on, and sends: ready once a chunk is there', async () => {
    const d = fakeDevices()
    holdDevices(d.handle)

    await expect(prepareRecording('s1')).resolves.toBe('ready')

    expect(startEventLog).toHaveBeenCalledWith('s1')
    expect(acquireDevices).not.toHaveBeenCalled() // no second prompt
    expect(startRecording).toHaveBeenCalledWith('s1', d.handle)
    expect(startUploader).toHaveBeenCalledWith('s1')
    expect(waitForUploads).toHaveBeenCalledWith(1, FIRST_UPLOAD_WAIT_MS)
    expect(FIRST_UPLOAD_WAIT_MS).toBe(30_000)
  })

  it('is slow, not failed, when nothing has reached the server in time', async () => {
    holdDevices(fakeDevices().handle)
    vi.mocked(waitForUploads).mockResolvedValue(false)
    await expect(prepareRecording('s1')).resolves.toBe('slow')
  })

  it('asks for the camera again if the page lost it (a reload on this page)', async () => {
    const d = fakeDevices()
    vi.mocked(acquireDevices).mockResolvedValue(d.handle)
    await expect(prepareRecording('s1')).resolves.toBe('ready')
    expect(startRecording).toHaveBeenCalledWith('s1', d.handle)
  })

  it('says no_devices, and records nothing, when the camera and microphone cannot be had', async () => {
    vi.mocked(acquireDevices).mockRejectedValue(new DOMException('no', 'NotAllowedError'))
    await expect(prepareRecording('s1')).resolves.toBe('no_devices')
    expect(startRecording).not.toHaveBeenCalled()
    expect(startUploader).not.toHaveBeenCalled()
  })

  it('says unsupported in a browser that cannot record, and lets the camera go', async () => {
    const d = fakeDevices()
    holdDevices(d.handle)
    vi.mocked(startRecording).mockRejectedValue(new RecorderUnsupportedError())

    await expect(prepareRecording('s1')).resolves.toBe('unsupported')
    expect(d.stop).toHaveBeenCalled()
  })

  it('says no_devices when the recorder fails for any other reason', async () => {
    holdDevices(fakeDevices().handle)
    vi.mocked(startRecording).mockRejectedValue(new Error('encoder'))
    await expect(prepareRecording('s1')).resolves.toBe('no_devices')
  })

  it('only waits, when pressed a second time, if it is already recording', async () => {
    vi.mocked(recordingState).mockReturnValue('recording')
    await expect(prepareRecording('s1')).resolves.toBe('ready')
    expect(startRecording).not.toHaveBeenCalled()
    expect(startUploader).toHaveBeenCalledWith('s1')
  })
})

describe('the test runtime', () => {
  const stops = { logger: vi.fn(), heartbeat: vi.fn(), mic: vi.fn() }

  beforeEach(() => {
    vi.clearAllMocks()
    vi.mocked(startActionLogger).mockReturnValue(stops.logger)
    vi.mocked(startHeartbeat).mockReturnValue(stops.heartbeat)
    vi.mocked(startMicWatch).mockReturnValue(stops.mic)
  })

  afterEach(async () => {
    await endTestRuntime()
  })

  it('starts everything a running test needs', () => {
    startTestRuntime('s1')

    expect(startEventLog).toHaveBeenCalledWith('s1')
    expect(startActionLogger).toHaveBeenCalledTimes(1)
    expect(startHeartbeat).toHaveBeenCalledTimes(1)
    expect(startMicWatch).toHaveBeenCalledTimes(1)
    expect(startUploader).toHaveBeenCalledWith('s1')
    expect(ensureRecording).toHaveBeenCalledWith('s1')
  })

  it('does not start the watchers twice if the test page is entered again', () => {
    startTestRuntime('s1')
    startTestRuntime('s1')
    expect(startActionLogger).toHaveBeenCalledTimes(1)
    expect(startHeartbeat).toHaveBeenCalledTimes(1)
  })

  it('stops them, and sends the whole log, at the end of the test', async () => {
    startTestRuntime('s1')
    await endTestRuntime()

    expect(stops.logger).toHaveBeenCalledTimes(1)
    expect(stops.heartbeat).toHaveBeenCalledTimes(1)
    expect(stops.mic).toHaveBeenCalledTimes(1)
    expect(flushEvents).toHaveBeenCalled()
  })

  it('can run again afterwards', async () => {
    startTestRuntime('s1')
    await endTestRuntime()
    startTestRuntime('s2')
    expect(startActionLogger).toHaveBeenCalledTimes(2)
  })

  it('ending a test that never started is harmless', async () => {
    await expect(endTestRuntime()).resolves.toBeUndefined()
  })
})
