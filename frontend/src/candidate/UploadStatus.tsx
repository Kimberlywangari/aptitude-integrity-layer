import { useEffect, useRef, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { api } from '../lib/api'
import type { ManifestResponse } from '../lib/api'
import { CANDIDATE_PATH } from '../lib/routes'
import { getSessionId } from '../lib/session'
import { UPLOAD_DONE, UPLOAD_KEEP_OPEN, UPLOAD_STUCK, UPLOAD_TITLE } from './copy'

const POLL_MS = 3000
const FAILURES_BEFORE_QUIT = 3
const STALLED_AFTER_MS = 60_000

// The page SEB's Quit URL points at. Plan A of the SEB spike (master plan R1): keep the
// candidate here until the upload is complete, then send them to it so SEB can close.
const QUIT_URL = import.meta.env.VITE_SEB_QUIT_URL ?? '/quit.html'

export default function UploadStatus() {
  const navigate = useNavigate()
  const sessionId = getSessionId()
  const [manifest, setManifest] = useState<ManifestResponse | null>(null)
  const [failures, setFailures] = useState(0)
  const [stalled, setStalled] = useState(false)
  const lastReceived = useRef(-1)
  const lastChangeAt = useRef(0)

  useEffect(() => {
    if (!sessionId) {
      navigate(CANDIDATE_PATH, { replace: true })
      return
    }
    lastChangeAt.current = performance.now()
    let stopped = false
    let timer: number | undefined

    async function poll() {
      try {
        const next = await api<ManifestResponse>(`/api/chunks/${sessionId}/manifest`)
        if (stopped) return
        setManifest(next)
        setFailures(0)
        if (next.received !== lastReceived.current) {
          lastReceived.current = next.received
          lastChangeAt.current = performance.now()
          setStalled(false)
        } else if (!next.complete && performance.now() - lastChangeAt.current > STALLED_AFTER_MS) {
          setStalled(true)
        }
        if (!next.complete) timer = window.setTimeout(() => void poll(), POLL_MS)
      } catch {
        if (stopped) return
        setFailures((n) => n + 1)
        timer = window.setTimeout(() => void poll(), POLL_MS)
      }
    }

    void poll()
    return () => {
      stopped = true
      window.clearTimeout(timer)
    }
  }, [sessionId, navigate])

  const complete = manifest?.complete === true
  const canQuitAnyway = !complete && (failures >= FAILURES_BEFORE_QUIT || stalled)
  const percent =
    manifest && manifest.expected ? Math.round((manifest.received / manifest.expected) * 100) : null

  function quit() {
    window.location.assign(QUIT_URL)
  }

  return (
    <main className="page">
      <h1>{UPLOAD_TITLE}</h1>

      {complete ? (
        <p role="status" className="ok">
          {UPLOAD_DONE}
        </p>
      ) : (
        <p>{UPLOAD_KEEP_OPEN}</p>
      )}

      {manifest && manifest.expected !== null && (
        <>
          <progress
            aria-label="Upload progress"
            max={manifest.expected}
            value={manifest.received}
          />
          <p className="muted">
            Uploaded {manifest.received} of {manifest.expected} parts
            {percent !== null && ` (${percent}%)`}.
          </p>
        </>
      )}
      {!manifest && failures === 0 && <p role="status">Checking your upload...</p>}
      {failures > 0 && !complete && (
        <p role="status" className="muted">
          Could not reach the server. Trying again.
        </p>
      )}

      {canQuitAnyway && (
        <p role="alert" className="error">
          {UPLOAD_STUCK}
        </p>
      )}

      <div className="actions">
        {complete && (
          <button type="button" onClick={quit}>
            Finish
          </button>
        )}
        {canQuitAnyway && (
          <button type="button" className="secondary" onClick={quit}>
            Quit anyway
          </button>
        )}
      </div>

      <p>
        <Link to="/complaint">Something went wrong? Tell us.</Link>
      </p>
    </main>
  )
}
