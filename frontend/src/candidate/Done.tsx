import { useEffect, useState } from 'react'
import type { FormEvent } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { api, pathForError } from '../lib/api'
import type { FinishResponse } from '../lib/api'
import { getSessionId } from '../lib/session'
import { SELF_REPORT_NOTE_HINT, SELF_REPORT_NOTE_LABEL, SELF_REPORT_QUESTION } from './copy'

export default function Done() {
  const navigate = useNavigate()
  const sessionId = getSessionId()
  const [summary, setSummary] = useState<FinishResponse | null>(null)
  const [issues, setIssues] = useState<boolean | null>(null)
  const [note, setNote] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  // Finishing is idempotent, so this is safe on every visit and after time-up.
  useEffect(() => {
    if (!sessionId) {
      navigate('/', { replace: true })
      return
    }
    api<FinishResponse>(`/api/session/${sessionId}/finish`, { method: 'POST' })
      .then(setSummary)
      .catch((e) => {
        const route = pathForError(e)
        if (route && route !== '/done') navigate(route, { replace: true })
      })
  }, [sessionId, navigate])

  async function submit(event: FormEvent) {
    event.preventDefault()
    if (!sessionId || issues === null) return
    setBusy(true)
    setError(null)
    try {
      await api(`/api/session/${sessionId}/self-report`, {
        method: 'POST',
        body: { had_technical_issues: issues, note: note.trim() || null },
      })
      // Recording upload carries on from here; the candidate waits for it on /uploading.
      navigate('/uploading', { replace: true })
    } catch {
      setError('Could not save that. Please try again.')
      setBusy(false)
    }
  }

  return (
    <main className="page">
      <h1>Test finished</h1>
      {summary && (
        <p>
          You answered {summary.answered} of {summary.total} questions.
        </p>
      )}

      <form onSubmit={submit}>
        <fieldset>
          <legend>{SELF_REPORT_QUESTION}</legend>
          <label className="option">
            <input
              type="radio"
              name="issues"
              checked={issues === false}
              onChange={() => setIssues(false)}
            />
            No
          </label>
          <label className="option">
            <input
              type="radio"
              name="issues"
              checked={issues === true}
              onChange={() => setIssues(true)}
            />
            Yes
          </label>
        </fieldset>

        {issues === true && (
          <>
            <label htmlFor="note">{SELF_REPORT_NOTE_LABEL}</label>
            <textarea
              id="note"
              value={note}
              maxLength={300}
              rows={4}
              onChange={(e) => setNote(e.target.value)}
            />
            <p className="muted">
              {SELF_REPORT_NOTE_HINT} ({note.length}/300)
            </p>
          </>
        )}

        <button type="submit" disabled={busy || issues === null}>
          {busy ? 'Sending...' : 'Send'}
        </button>
        {error && (
          <p role="alert" className="error">
            {error}
          </p>
        )}
      </form>

      <p>
        <Link to="/complaint">Camera or upload trouble? Tell us.</Link>
      </p>
    </main>
  )
}
