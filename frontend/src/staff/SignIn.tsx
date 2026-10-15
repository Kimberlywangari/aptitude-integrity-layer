import { useState } from 'react'
import type { FormEvent } from 'react'
import { Link, Navigate, useNavigate, useSearchParams } from 'react-router-dom'
import { api, ApiError } from '../lib/api'
import { homeFor, LOGIN_PATH, safeNext } from '../lib/routes'
import type { LoginResponse } from '../lib/reviewTypes'
import { getStaff, saveStaff } from '../lib/staffSession'
import type { StaffRole } from '../lib/staffSession'
import { waitPhrase } from '../lib/wait'

type Area = StaffRole

const COPY: Record<Area, { title: string; lead: string; other: Area; otherLabel: string }> = {
  reviewer: {
    title: 'Reviewer sign in',
    lead: 'For people who review flagged candidates.',
    other: 'admin',
    otherLabel: 'Setting up a sitting? Admin sign in',
  },
  admin: {
    title: 'Admin sign in',
    lead: 'For people who set up sittings, questions and invitations.',
    other: 'reviewer',
    otherLabel: 'Reviewing candidates? Reviewer sign in',
  },
}

type Problem =
  | { kind: 'credentials' }
  | { kind: 'wrong-area' }
  | { kind: 'too-many'; seconds: number }
  | { kind: 'other' }

function describe(problem: Problem): string {
  switch (problem.kind) {
    case 'credentials':
      return 'The email or password is not right.'
    case 'wrong-area':
      return 'This account is a reviewer account, which cannot open the admin pages.'
    case 'too-many':
      return `Too many wrong attempts. Please wait ${waitPhrase(problem.seconds)} and try again.`
    default:
      return 'Something went wrong. Please try again.'
  }
}

export default function SignIn({ area }: { area: Area }) {
  const navigate = useNavigate()
  const [params] = useSearchParams()
  const next = safeNext(params.get('next'))
  const copy = COPY[area]
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [busy, setBusy] = useState(false)
  const [problem, setProblem] = useState<Problem | null>(null)

  // The reviewer card is open to admins too (they can see the review pages) and lands on the
  // queue; the admin card is not open to reviewers, so a signed-in reviewer is sent to the queue.
  const landing = (role: StaffRole) => (area === 'admin' ? homeFor(role) : '/review')

  const existing = getStaff()
  if (existing) return <Navigate to={next ?? landing(existing.role)} replace />

  async function submit(event: FormEvent) {
    event.preventDefault()
    setBusy(true)
    setProblem(null)
    try {
      const session = await api<LoginResponse>('/api/review/login', {
        method: 'POST',
        body: { email: email.trim(), password },
      })
      if (area === 'admin' && session.role !== 'admin') {
        // Signed in, but not for this door: keep nothing, say so.
        setProblem({ kind: 'wrong-area' })
        setBusy(false)
        return
      }
      saveStaff(session)
      navigate(next ?? landing(session.role), { replace: true })
    } catch (e) {
      if (e instanceof ApiError && e.code === 'invalid_credentials') {
        setProblem({ kind: 'credentials' })
      } else if (e instanceof ApiError && e.code === 'too_many_attempts') {
        const seconds = typeof e.body.retry_after_s === 'number' ? e.body.retry_after_s : 60
        setProblem({ kind: 'too-many', seconds })
      } else {
        setProblem({ kind: 'other' })
      }
      setBusy(false)
    }
  }

  return (
    <main className="page narrow">
      <p className="back">
        <Link to="/">All sign-ins</Link>
      </p>
      <h1>{copy.title}</h1>
      <p className="muted">{copy.lead}</p>
      <form onSubmit={submit}>
        <label htmlFor="email">Email</label>
        <input
          id="email"
          type="email"
          autoComplete="username"
          autoFocus
          value={email}
          onChange={(e) => setEmail(e.target.value)}
        />
        <label htmlFor="password">Password</label>
        <input
          id="password"
          type="password"
          autoComplete="current-password"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
        />
        <button type="submit" disabled={busy || !email.trim() || !password}>
          {busy ? 'Signing in...' : 'Sign in'}
        </button>
      </form>
      {problem && (
        <p role="alert" className="error">
          {describe(problem)}
          {problem.kind === 'wrong-area' && (
            <>
              {' '}
              <Link to={LOGIN_PATH.reviewer}>Use the reviewer sign in</Link>.
            </>
          )}
        </p>
      )}
      <p className="muted switch">
        <Link to={LOGIN_PATH[copy.other]}>{copy.otherLabel}</Link>
      </p>
    </main>
  )
}
