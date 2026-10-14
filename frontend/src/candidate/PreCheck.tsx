import { useCallback, useEffect, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { api, ApiError, pathForError } from '../lib/api'
import type { PrecheckRequest, PrecheckResponse } from '../lib/api'
import { acquireDevices, classifyDeviceError } from '../lib/devices'
import type { DeviceErrorKind, DeviceHandle } from '../lib/devices'
import { INITIAL_MIC_CHECK, stepMicCheck } from '../lib/micCheck'
import type { MicCheckState } from '../lib/micCheck'
import { getSessionId } from '../lib/session'
import {
  DEVICE_ERRORS,
  DEVICE_NOTICE_CHECKBOX,
  DEVICE_NOTICE_POINTS,
  DEVICE_NOTICE_TITLE,
  MIC_MUTED_MESSAGE,
  MIC_PROMPT,
  MIC_QUIET_MESSAGE,
} from './copy'

const TICK_MS = 100
const METER_MAX = 0.1

type Phase = 'idle' | 'starting' | 'live'

export default function PreCheck() {
  const navigate = useNavigate()
  const sessionId = getSessionId()

  const [understood, setUnderstood] = useState(false)
  const [phase, setPhase] = useState<Phase>('idle')
  const [deviceError, setDeviceError] = useState<DeviceErrorKind | null>(null)
  const [cameraOk, setCameraOk] = useState(false)
  const [mic, setMic] = useState<MicCheckState>(INITIAL_MIC_CHECK)
  const [level, setLevel] = useState(0)
  const [muted, setMuted] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const devices = useRef<DeviceHandle | null>(null)
  const preview = useRef<HTMLVideoElement>(null)
  const peak = useRef(0)

  useEffect(() => {
    if (!sessionId) navigate('/', { replace: true })
  }, [sessionId, navigate])

  // Release the camera and microphone when the candidate leaves this screen.
  useEffect(
    () => () => {
      devices.current?.stop()
      devices.current = null
    },
    [],
  )

  const start = useCallback(async () => {
    setPhase('starting')
    setDeviceError(null)
    setMic(INITIAL_MIC_CHECK)
    setMuted(false)
    peak.current = 0
    devices.current?.stop()
    try {
      const handle = await acquireDevices()
      devices.current = handle
      setCameraOk(handle.stream.getVideoTracks()[0]?.readyState === 'live')
      setPhase('live')
    } catch (e) {
      devices.current = null
      setCameraOk(false)
      setDeviceError(classifyDeviceError(e))
      setPhase('idle')
    }
  }, [])

  // Show the live picture once the stream exists.
  useEffect(() => {
    if (phase === 'live' && preview.current && devices.current) {
      preview.current.srcObject = devices.current.stream
    }
  }, [phase])

  // Level meter and the "say your name" check.
  useEffect(() => {
    if (phase !== 'live' || mic.result !== 'listening') return
    const id = window.setInterval(() => {
      const handle = devices.current
      if (!handle) return
      const isMuted = handle.micMuted()
      setMuted(isMuted)
      const { rms, peak: p } = handle.readMicLevel()
      peak.current = Math.max(peak.current, p)
      setLevel(isMuted ? 0 : rms)
      setMic((state) => stepMicCheck(state, isMuted ? 0 : rms, TICK_MS))
    }, TICK_MS)
    return () => window.clearInterval(id)
  }, [phase, mic.result])

  async function proceed() {
    const handle = devices.current
    if (!sessionId || !handle) return
    setBusy(true)
    setError(null)
    const body: PrecheckRequest = {
      camera_ok: cameraOk,
      mic_ok: mic.result === 'passed',
      device_labels: { camera: handle.cameraLabel, mic: handle.micLabel },
      mic_peak: Number(peak.current.toFixed(4)),
      video_size: handle.videoSize,
    }
    try {
      const result = await api<PrecheckResponse>('/api/precheck/result', {
        method: 'POST',
        body,
      })
      if (!result.passed) {
        setError('The check did not pass. Please try again.')
        setBusy(false)
        return
      }
      handle.stop()
      devices.current = null
      navigate('/integrity', { replace: true })
    } catch (e) {
      const route = pathForError(e)
      if (route && route !== '/precheck') navigate(route, { replace: true })
      else if (!(e instanceof ApiError && e.code === 'seb_required'))
        setError('Something went wrong. Please try again.')
      setBusy(false)
    }
  }

  const micPassed = mic.result === 'passed'
  const canContinue = understood && cameraOk && micPassed && !busy

  return (
    <main className="page">
      <h1>{DEVICE_NOTICE_TITLE}</h1>

      <ol className="steps">
        <li>
          <h2>1. Before you start</h2>
          <ul className="statement">
            {DEVICE_NOTICE_POINTS.map((point) => (
              <li key={point}>{point}</li>
            ))}
          </ul>
          <label className="check">
            <input
              type="checkbox"
              checked={understood}
              onChange={(e) => setUnderstood(e.target.checked)}
            />
            {DEVICE_NOTICE_CHECKBOX}
          </label>
          {phase !== 'live' && (
            <button
              type="button"
              disabled={!understood || phase === 'starting'}
              onClick={() => void start()}
            >
              {phase === 'starting' ? 'Starting...' : 'Check my camera and microphone'}
            </button>
          )}
          {deviceError && (
            <p role="alert" className="error">
              {DEVICE_ERRORS[deviceError]}
            </p>
          )}
        </li>

        <li>
          <h2>2. Camera</h2>
          {phase === 'live' ? (
            <>
              <video ref={preview} className="preview" autoPlay muted playsInline />
              <p role="status" className={cameraOk ? 'ok' : 'error'}>
                {cameraOk ? 'Camera working.' : 'The camera is not sending a picture.'}
              </p>
            </>
          ) : (
            <p className="muted">Your picture appears here after step 1.</p>
          )}
        </li>

        <li>
          <h2>3. Microphone</h2>
          {phase === 'live' ? (
            <>
              <p>{MIC_PROMPT}</p>
              <meter
                aria-label="Microphone level"
                min={0}
                max={METER_MAX}
                value={Math.min(level, METER_MAX)}
              />
              {muted && (
                <p role="alert" className="error">
                  {MIC_MUTED_MESSAGE}
                </p>
              )}
              {micPassed && (
                <p role="status" className="ok">
                  Microphone working.
                </p>
              )}
              {mic.result === 'failed' && (
                <>
                  <p role="alert" className="error">
                    {muted ? MIC_MUTED_MESSAGE : MIC_QUIET_MESSAGE}
                  </p>
                  <button type="button" className="secondary" onClick={() => setMic(INITIAL_MIC_CHECK)}>
                    Try the microphone again
                  </button>
                </>
              )}
            </>
          ) : (
            <p className="muted">The level meter appears here after step 1.</p>
          )}
        </li>

        <li>
          <h2>4. Continue</h2>
          <button type="button" disabled={!canContinue} onClick={() => void proceed()}>
            {busy ? 'Checking...' : 'Continue to the test'}
          </button>
          {error && (
            <p role="alert" className="error">
              {error}
            </p>
          )}
        </li>
      </ol>
    </main>
  )
}
