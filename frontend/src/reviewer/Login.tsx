import { useState } from 'react'
import type { FormEvent } from 'react'
import { Navigate, useNavigate, useSearchParams } from 'react-router-dom'
import { api, ApiError } from '../lib/api'
import type { LoginResponse } from '../lib/reviewTypes'
import { getStaff, saveStaff } from '../lib/staffSession'

/** Only ever return to a staff page, never an arbitrary address. */
function safeNext(next: string | null): string | null {
  return next && /^\/(review|admin)(\/|\?|$)/.test(next) ? next : null
}

export default function Login() {
  const navigate = useNavigate()
  const [params] = useSearchParams()
  const next = safeNext(params.get('next'))
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const existing = getStaff()
  if (existing) {
    return <Navigate to={next ?? (existing.role === 'admin' ? '/admin' : '/review')} replace />
  }

  async function submit(event: FormEvent) {
    event.preventDefault()
    setBusy(true)
    setError(null)
    try {
      const session = await api<LoginResponse>('/api/review/login', {
        method: 'POST',
        body: { email: email.trim(), password },
      })
      saveStaff(session)
      navigate(next ?? (session.role === 'admin' ? '/admin' : '/review'), { replace: true })
    } catch (e) {
      setError(
        e instanceof ApiError && e.code === 'invalid_credentials'
          ? 'The email or password is not right.'
          : 'Something went wrong. Please try again.',
      )
      setBusy(false)
    }
  }

  return (
    <main className="page">
      <h1>Sign in</h1>
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
      {error && (
        <p role="alert" className="error">
          {error}
        </p>
      )}
    </main>
  )
}
