import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { api, ApiError, pathForError } from '../lib/api'
import type { BeginResponse } from '../lib/api'
import { getSessionId } from '../lib/session'
import { INTEGRITY_CHECKBOX, INTEGRITY_POINTS, INTEGRITY_TITLE } from './copy'

export default function Integrity() {
  const navigate = useNavigate()
  const sessionId = getSessionId()
  const [agreed, setAgreed] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (!sessionId) navigate('/', { replace: true })
  }, [sessionId, navigate])

  async function begin() {
    if (!sessionId) return
    setBusy(true)
    setError(null)
    try {
      // The server starts the timer now, not when the page was opened.
      await api<BeginResponse>(`/api/session/${sessionId}/begin`, {
        method: 'POST',
        body: { accepted: true },
      })
      navigate('/test', { replace: true })
    } catch (e) {
      const route = pathForError(e)
      if (route && route !== '/integrity') navigate(route, { replace: true })
      else if (!(e instanceof ApiError && e.code === 'seb_required'))
        setError('Something went wrong. Please try again.')
      setBusy(false)
    }
  }

  return (
    <main className="page">
      <h1>{INTEGRITY_TITLE}</h1>
      <ul className="statement">
        {INTEGRITY_POINTS.map((point) => (
          <li key={point}>{point}</li>
        ))}
      </ul>
      <label className="check">
        <input type="checkbox" checked={agreed} onChange={(e) => setAgreed(e.target.checked)} />
        {INTEGRITY_CHECKBOX}
      </label>
      <p className="muted">Your time starts as soon as you press the button below.</p>
      <button type="button" disabled={!agreed || busy} onClick={begin}>
        {busy ? 'Starting...' : 'I agree, start the test'}
      </button>
      {error && (
        <p role="alert" className="error">
          {error}
        </p>
      )}
    </main>
  )
}
