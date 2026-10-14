import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import type { FormEvent } from 'react'
import { Link } from 'react-router-dom'
import { api, ApiError } from '../lib/api'
import type {
  AdminSitting,
  CloseSittingResponse,
  CreateSittingRequest,
  QuestionBankSummary,
} from '../lib/adminTypes'
import { formatDateTime } from '../lib/format'

const CREATE_ERRORS: Record<string, string> = {
  name_required: 'Give the sitting a name.',
  invalid_duration: 'The duration must be at least one minute.',
  invalid_question_count: 'The sitting needs at least one question.',
}

function createMessage(error: unknown): string | null {
  if (!error) return null
  if (error instanceof ApiError) {
    if (error.code === 'question_bank_too_small') {
      return `The question bank has only ${String(error.body.available ?? 'a few')} questions.`
    }
    return CREATE_ERRORS[error.code] ?? 'Could not create the sitting.'
  }
  return 'Could not create the sitting.'
}

function toIso(local: string): string | null {
  if (!local) return null
  const date = new Date(local)
  return Number.isNaN(date.getTime()) ? null : date.toISOString()
}

export default function Sittings() {
  const queryClient = useQueryClient()
  const [name, setName] = useState('')
  const [opensAt, setOpensAt] = useState('')
  const [closesAt, setClosesAt] = useState('')
  const [minutes, setMinutes] = useState(30)
  const [count, setCount] = useState(12)
  const [needsForce, setNeedsForce] = useState<{ id: number; unfinished: number } | null>(null)
  const [closeError, setCloseError] = useState<string | null>(null)

  const sittings = useQuery({
    queryKey: ['admin', 'sittings'],
    queryFn: () => api<{ sittings: AdminSitting[] }>('/api/admin/sittings'),
  })
  const bank = useQuery({
    queryKey: ['admin', 'bank'],
    queryFn: () => api<QuestionBankSummary>('/api/admin/questions/summary'),
  })

  const create = useMutation({
    mutationFn: (body: CreateSittingRequest) =>
      api<AdminSitting>('/api/admin/sittings', { method: 'POST', body }),
    onSuccess: async () => {
      setName('')
      await queryClient.invalidateQueries({ queryKey: ['admin', 'sittings'] })
    },
  })

  const close = useMutation({
    mutationFn: (vars: { id: number; force: boolean }) =>
      api<CloseSittingResponse>(`/api/admin/sittings/${vars.id}/close`, {
        method: 'POST',
        body: { force: vars.force },
      }),
    onSuccess: async () => {
      setNeedsForce(null)
      setCloseError(null)
      await queryClient.invalidateQueries({ queryKey: ['admin', 'sittings'] })
    },
    onError: (error, vars) => {
      if (error instanceof ApiError && error.code === 'sessions_unfinished') {
        setNeedsForce({ id: vars.id, unfinished: Number(error.body.unfinished ?? 0) })
        setCloseError(null)
      } else {
        setCloseError('Could not close the sitting.')
      }
    },
  })

  function submit(event: FormEvent) {
    event.preventDefault()
    create.mutate({
      name: name.trim(),
      opens_at: toIso(opensAt),
      closes_at: toIso(closesAt),
      duration_s: Math.round(minutes * 60),
      question_count: Math.round(count),
    })
  }

  return (
    <>
      <h1>Sittings</h1>

      {bank.data && bank.data.synthetic > 0 && (
        <p role="status" className="banner">
          {bank.data.synthetic} placeholder questions are still in the question bank and can
          appear on real papers. <Link to="/admin/questions">Remove them</Link> before a real
          sitting.
        </p>
      )}

      <section className="panel">
        <h2>New sitting</h2>
        <form onSubmit={submit}>
          <label htmlFor="name">Name</label>
          <input id="name" value={name} onChange={(e) => setName(e.target.value)} />
          <div className="field-row">
            <div>
              <label htmlFor="opens">Opens (optional)</label>
              <input
                id="opens"
                type="datetime-local"
                value={opensAt}
                onChange={(e) => setOpensAt(e.target.value)}
              />
            </div>
            <div>
              <label htmlFor="closes">Closes (optional)</label>
              <input
                id="closes"
                type="datetime-local"
                value={closesAt}
                onChange={(e) => setClosesAt(e.target.value)}
              />
            </div>
          </div>
          <div className="field-row">
            <div>
              <label htmlFor="minutes">Time limit (minutes)</label>
              <input
                id="minutes"
                type="number"
                min={1}
                value={minutes}
                onChange={(e) => setMinutes(Number(e.target.value))}
              />
            </div>
            <div>
              <label htmlFor="count">Questions per candidate</label>
              <input
                id="count"
                type="number"
                min={1}
                value={count}
                onChange={(e) => setCount(Number(e.target.value))}
              />
            </div>
          </div>
          <button type="submit" disabled={create.isPending || !name.trim()}>
            {create.isPending ? 'Creating...' : 'Create sitting'}
          </button>
        </form>
        {create.isError && (
          <p role="alert" className="error">
            {createMessage(create.error)}
          </p>
        )}
      </section>

      {sittings.isPending && <p role="status">Loading sittings...</p>}
      {sittings.isError && (
        <p role="alert" className="error">
          Could not load the sittings.
        </p>
      )}
      {sittings.data && (
        <div className="table-wrap">
          <table className="table">
            <thead>
              <tr>
                <th>Name</th>
                <th>Window</th>
                <th>Limit</th>
                <th>Questions</th>
                <th>Progress</th>
                <th>Status</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {sittings.data.sittings.map((s) => {
                const total = s.counts.finished + s.counts.in_progress + s.counts.not_started
                return (
                  <tr key={s.id}>
                    <td>{s.name}</td>
                    <td>
                      {s.opens_at || s.closes_at
                        ? `${formatDateTime(s.opens_at)} to ${formatDateTime(s.closes_at)}`
                        : 'Always open'}
                    </td>
                    <td>{Math.round(s.duration_s / 60)} min</td>
                    <td>{s.question_count}</td>
                    <td>
                      {s.counts.finished} of {total} finished
                      {s.counts.in_progress > 0 && `, ${s.counts.in_progress} sitting now`}
                    </td>
                    <td>{s.status === 'open' ? 'Open' : 'Closed'}</td>
                    <td>
                      {s.status === 'open' &&
                        (needsForce?.id === s.id ? (
                          <>
                            <span className="muted">{needsForce.unfinished} not finished. </span>
                            <button
                              type="button"
                              disabled={close.isPending}
                              onClick={() => close.mutate({ id: s.id, force: true })}
                            >
                              Close anyway (logged)
                            </button>
                          </>
                        ) : (
                          <button
                            type="button"
                            className="secondary"
                            disabled={close.isPending}
                            onClick={() => close.mutate({ id: s.id, force: false })}
                          >
                            Close sitting
                          </button>
                        ))}
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      )}
      {closeError && (
        <p role="alert" className="error">
          {closeError}
        </p>
      )}
      <p className="muted">
        Flags and packets are built after a sitting is closed. Cohort checks need at least 8
        finished candidates.
      </p>
    </>
  )
}
