import { useEffect, useRef, useState } from 'react'
import type { FormEvent } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { api, ApiError } from '../lib/api'
import type { SessionStatus, StartResponse } from '../lib/api'
import { normaliseInviteCode } from '../lib/inviteCode'
import { saveSession } from '../lib/session'

const MESSAGES: Record<string, string> = {
  invalid_invitation: 'That invitation is not valid. Check the link or code you were sent.',
  no_open_sitting: 'This test is not open right now.',
  too_many_attempts: 'Too many wrong codes. Please wait a few minutes and try again.',
}

function routeFor(status: SessionStatus): string {
  if (status === 'in_progress') return '/test'
  if (status === 'finished') return '/done'
  return '/precheck' // device check first; it hands over to /integrity
}

export default function Start() {
  const navigate = useNavigate()
  const [params] = useSearchParams()
  const [token, setToken] = useState(params.get('t') ?? '')
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const autoStarted = useRef(false)

  async function start(invitation: string) {
    setBusy(true)
    setError(null)
    try {
      const body = await api<StartResponse>('/api/session/start', {
        method: 'POST',
        // Typed by hand inside SEB, so case, dashes and spaces are forgiven (lib/inviteCode.ts).
        body: { token: normaliseInviteCode(invitation) },
      })
      saveSession(body.session_id, body.access_token)
      navigate(routeFor(body.status), { replace: true })
    } catch (e) {
      // seb_required is handled globally (it navigates to /not-seb)
      if (e instanceof ApiError && e.code === 'seb_required') return
      setError(
        e instanceof ApiError && MESSAGES[e.code]
          ? MESSAGES[e.code]
          : 'Something went wrong. Please try again.',
      )
      setBusy(false)
    }
  }

  // An invitation link carries the token as ?t=..., so the candidate doesn't have to type it.
  useEffect(() => {
    const fromLink = params.get('t')
    if (fromLink && !autoStarted.current) {
      autoStarted.current = true
      void start(fromLink)
    }
  }, [])

  function onSubmit(event: FormEvent) {
    event.preventDefault()
    if (token.trim()) void start(token)
  }

  return (
    <main className="page">
      <h1>Aptitude test</h1>
      <form onSubmit={onSubmit}>
        <label htmlFor="invitation">Invitation code</label>
        <input
          id="invitation"
          value={token}
          onChange={(e) => setToken(e.target.value)}
          autoComplete="off"
          autoCorrect="off"
          spellCheck={false}
          placeholder="XXXX-XXXX"
          autoFocus
          disabled={busy}
        />
        <button type="submit" disabled={busy || !token.trim()}>
          {busy ? 'Starting...' : 'Continue'}
        </button>
      </form>
      {error && (
        <p role="alert" className="error">
          {error}
        </p>
      )}
    </main>
  )
}
