import { useMutation, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import type { FormEvent } from 'react'
import { api, ApiError } from '../lib/api'
import { MIN_REASON_CHARS } from '../lib/reviewTypes'
import type { DecisionOutcome, DecisionRequest } from '../lib/reviewTypes'
import { OUTCOME_LABELS, OUTCOMES_NOTE } from './copy'

const ERRORS: Record<string, string> = {
  reason_too_short: `The reason must be at least ${MIN_REASON_CHARS} characters.`,
  invalid_outcome: 'Choose one of the outcomes.',
}

interface Props {
  sessionId: string
  candidateId: string
}

export default function DecisionForm({ sessionId, candidateId }: Props) {
  const queryClient = useQueryClient()
  const [outcome, setOutcome] = useState<DecisionOutcome | ''>('')
  const [reason, setReason] = useState('')
  const [confirmed, setConfirmed] = useState(false)
  const [saved, setSaved] = useState(false)

  const save = useMutation({
    mutationFn: (body: DecisionRequest) =>
      api<{ decided_at: string }>('/api/review/decisions', { method: 'POST', body }),
    onSuccess: async () => {
      setSaved(true)
      setOutcome('')
      setReason('')
      setConfirmed(false)
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ['candidate', candidateId] }),
        queryClient.invalidateQueries({ queryKey: ['queue'] }),
        queryClient.invalidateQueries({ queryKey: ['audit'] }),
      ])
    },
  })

  const trimmed = reason.trim()
  const valid = outcome !== '' && trimmed.length >= MIN_REASON_CHARS && confirmed

  function submit(event: FormEvent) {
    event.preventDefault()
    if (!valid) return
    setSaved(false)
    save.mutate({ session_id: sessionId, outcome, reason: trimmed })
  }

  const error = save.error
  const message =
    error instanceof ApiError
      ? (ERRORS[error.code] ?? 'Could not save the decision. Please try again.')
      : error
        ? 'Could not save the decision. Please try again.'
        : null

  return (
    <form className="panel" onSubmit={submit}>
      <h2>Your decision</h2>
      <fieldset>
        <legend>Outcome</legend>
        {(Object.keys(OUTCOME_LABELS) as DecisionOutcome[]).map((value) => (
          <label key={value} className="option">
            <input
              type="radio"
              name="outcome"
              value={value}
              checked={outcome === value}
              onChange={() => setOutcome(value)}
            />
            {OUTCOME_LABELS[value]}
          </label>
        ))}
        <p className="muted">{OUTCOMES_NOTE}</p>
      </fieldset>

      <label htmlFor="reason">Reason (required, at least {MIN_REASON_CHARS} characters)</label>
      <textarea
        id="reason"
        rows={4}
        value={reason}
        onChange={(e) => setReason(e.target.value)}
      />
      <p className="muted">{trimmed.length} characters</p>

      <label className="check">
        <input
          type="checkbox"
          checked={confirmed}
          onChange={(e) => setConfirmed(e.target.checked)}
        />
        I have looked at the evidence and this reason is mine.
      </label>

      <button type="submit" disabled={!valid || save.isPending}>
        {save.isPending ? 'Saving...' : 'Record decision'}
      </button>

      {saved && <p role="status">Decision recorded.</p>}
      {message && (
        <p role="alert" className="error">
          {message}
        </p>
      )}
    </form>
  )
}
