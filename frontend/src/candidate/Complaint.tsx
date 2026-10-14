import { useEffect, useState } from 'react'
import type { FormEvent } from 'react'
import { useNavigate } from 'react-router-dom'
import { api, ApiError, pathForError } from '../lib/api'
import type { ComplaintCategory, ComplaintRequest } from '../lib/api'
import { CANDIDATE_PATH } from '../lib/routes'
import { getSessionId } from '../lib/session'
import {
  COMPLAINT_CATEGORIES,
  COMPLAINT_NOTE_LABEL,
  COMPLAINT_THANKS,
  COMPLAINT_TITLE,
} from './copy'

const MAX_CHARS = 1000

export default function Complaint() {
  const navigate = useNavigate()
  const sessionId = getSessionId()
  const [category, setCategory] = useState<ComplaintCategory | null>(null)
  const [text, setText] = useState('')
  const [busy, setBusy] = useState(false)
  const [sent, setSent] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (!sessionId) navigate(CANDIDATE_PATH, { replace: true })
  }, [sessionId, navigate])

  async function submit(event: FormEvent) {
    event.preventDefault()
    if (!category || !text.trim()) return
    setBusy(true)
    setError(null)
    const body: ComplaintRequest = { category, text: text.trim() }
    try {
      await api('/api/complaints', { method: 'POST', body })
      setSent(true)
    } catch (e) {
      const route = pathForError(e)
      if (route && route !== '/complaint') navigate(route, { replace: true })
      else if (!(e instanceof ApiError && e.code === 'seb_required'))
        setError('Could not send that. Please try again.')
    } finally {
      setBusy(false)
    }
  }

  return (
    <main className="page">
      <h1>{COMPLAINT_TITLE}</h1>

      {sent ? (
        <>
          <p role="status">{COMPLAINT_THANKS}</p>
          <button type="button" className="secondary" onClick={() => navigate(-1)}>
            Back
          </button>
        </>
      ) : (
        <form onSubmit={submit}>
          <fieldset>
            <legend className="sr-only">What kind of problem</legend>
            {COMPLAINT_CATEGORIES.map((c) => (
              <label key={c.value} className="option">
                <input
                  type="radio"
                  name="category"
                  checked={category === c.value}
                  onChange={() => setCategory(c.value)}
                />
                {c.label}
              </label>
            ))}
          </fieldset>

          <label htmlFor="text">{COMPLAINT_NOTE_LABEL}</label>
          <textarea
            id="text"
            rows={5}
            maxLength={MAX_CHARS}
            value={text}
            onChange={(e) => setText(e.target.value)}
          />
          <p className="muted">
            {text.length}/{MAX_CHARS}
          </p>

          <div className="actions">
            <button type="submit" disabled={busy || !category || !text.trim()}>
              {busy ? 'Sending...' : 'Send'}
            </button>
            <button type="button" className="secondary" onClick={() => navigate(-1)}>
              Back
            </button>
          </div>
          {error && (
            <p role="alert" className="error">
              {error}
            </p>
          )}
        </form>
      )}
    </main>
  )
}
