import { useCallback, useEffect, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { api, ApiError, pathForError } from '../lib/api'
import type { QuestionResponse, ResolveResponse } from '../lib/api'
import { getSessionId } from '../lib/session'

interface Clock {
  remaining: number // seconds left, as the server said
  syncedAt: number // performance.now() when the server said it
}

function format(seconds: number): string {
  const whole = Math.max(0, Math.ceil(seconds))
  const m = Math.floor(whole / 60)
  const s = whole % 60
  return `${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}`
}

export default function TestRunner() {
  const navigate = useNavigate()
  const sessionId = getSessionId()
  const [question, setQuestion] = useState<QuestionResponse | null>(null)
  const [selected, setSelected] = useState<number | null>(null)
  const [clock, setClock] = useState<Clock | null>(null)
  const [left, setLeft] = useState<number | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const refreshing = useRef(false)

  const sync = useCallback((remaining: number) => {
    setClock({ remaining, syncedAt: performance.now() })
  }, [])

  // Where to go, or a message, for any failure from the flow.
  const handleError = useCallback(
    (e: unknown) => {
      const route = pathForError(e)
      if (route) {
        navigate(route, { replace: true })
        return
      }
      if (e instanceof ApiError && e.code === 'seb_required') return
      setError('Could not reach the server. Your answers so far are safe. Please try again.')
    },
    [navigate],
  )

  const load = useCallback(async () => {
    if (!sessionId) {
      navigate('/', { replace: true })
      return
    }
    try {
      const q = await api<QuestionResponse>(`/api/session/${sessionId}/question`)
      setQuestion(q)
      setSelected(null)
      setError(null)
      sync(q.remaining_s)
    } catch (e) {
      handleError(e)
    }
  }, [sessionId, navigate, handleError, sync])

  // The question comes from the server on every load, so a reload keeps the same question and
  // the same time left.
  useEffect(() => {
    void load()
  }, [load])

  // No Back: keep the page on the same history entry, and ask before a reload or close.
  useEffect(() => {
    history.pushState(null, '', location.href)
    const onPop = () => history.pushState(null, '', location.href)
    const onBeforeUnload = (event: BeforeUnloadEvent) => {
      event.preventDefault()
      event.returnValue = ''
    }
    window.addEventListener('popstate', onPop)
    window.addEventListener('beforeunload', onBeforeUnload)
    return () => {
      window.removeEventListener('popstate', onPop)
      window.removeEventListener('beforeunload', onBeforeUnload)
    }
  }, [])

  // Countdown: counted from the server's remaining_s, re-synced on every response, never from
  // the device's wall clock.
  useEffect(() => {
    if (!clock) return
    const tick = () => {
      const value = Math.max(0, clock.remaining - (performance.now() - clock.syncedAt) / 1000)
      setLeft(value)
      if (value <= 0 && !refreshing.current) {
        refreshing.current = true
        // Ask the server: it answers 410 time_up (-> /done), or re-syncs if it disagrees.
        void load().finally(() => {
          refreshing.current = false
        })
      }
    }
    tick()
    const id = window.setInterval(tick, 250)
    return () => window.clearInterval(id)
  }, [clock, load])

  async function resolve(kind: 'answer' | 'skip') {
    if (!question || !sessionId || busy) return
    if (kind === 'answer' && selected === null) return
    setBusy(true)
    setError(null)
    try {
      const result = await api<ResolveResponse>(`/api/session/${sessionId}/${kind}`, {
        method: 'POST',
        body:
          kind === 'answer'
            ? { position: question.position, option_id: selected }
            : { position: question.position },
      })
      if (result.done) {
        navigate('/done', { replace: true })
        return
      }
      sync(result.remaining_s)
      await load()
    } catch (e) {
      if (e instanceof ApiError && e.code === 'not_current') await load()
      else handleError(e)
    } finally {
      setBusy(false)
    }
  }

  if (!question) {
    return (
      <main className="page">
        <p role="status">{error ?? 'Loading your question...'}</p>
        {error && <button onClick={() => void load()}>Try again</button>}
      </main>
    )
  }

  return (
    <main className="page test">
      <header className="test-header">
        <span>
          Question {question.position} of {question.total}
        </span>
        <span role="timer" className="timer">
          {left === null ? '--:--' : format(left)}
        </span>
      </header>

      <p className="section">{question.section}</p>
      <p id="question-text" className="question-text">
        {question.text}
      </p>

      <fieldset disabled={busy}>
        <legend className="sr-only">Choose one answer</legend>
        {question.options.map((option) => (
          <label key={option.id} className="option">
            <input
              type="radio"
              name="answer"
              value={option.id}
              checked={selected === option.id}
              onChange={() => setSelected(option.id)}
            />
            {option.text}
          </label>
        ))}
      </fieldset>

      <div className="actions">
        <button type="button" disabled={busy || selected === null} onClick={() => resolve('answer')}>
          Submit
        </button>
        <button type="button" className="secondary" disabled={busy} onClick={() => resolve('skip')}>
          Skip
        </button>
      </div>
      <p className="muted">You cannot come back to a question once you move on.</p>

      {error && (
        <p role="alert" className="error">
          {error}
        </p>
      )}
    </main>
  )
}
