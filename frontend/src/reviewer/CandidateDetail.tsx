import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useRef, useState } from 'react'
import type { ReactNode } from 'react'
import { Link, useParams } from 'react-router-dom'
import { api, ApiError } from '../lib/api'
import { formatDateTime, formatElapsed, humaniseKind, ordinal } from '../lib/format'
import type {
  CandidateDetail as Detail,
  FlagItem,
  InnocentSignal,
  VideoSeek,
  VsSitting,
} from '../lib/reviewTypes'
import {
  AI_LABEL,
  CONTEXT_ONLY,
  DETAIL_LABELS,
  FLAG_LABELS,
  INNOCENT_LABELS,
  OUTCOME_LABELS,
  RETENTION_NOTE,
  RULES_LABEL,
  orderBasis,
} from './copy'
import DecisionForm from './DecisionForm'
import VideoPlayer from './VideoPlayer'
import type { JumpTarget } from './VideoPlayer'

function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className="panel">
      <h2>{title}</h2>
      {children}
    </section>
  )
}

function detailText(detail: Record<string, unknown>): string {
  return Object.entries(detail)
    .map(([key, value]) => {
      const shown = Array.isArray(value)
        ? value.join(', ')
        : typeof value === 'boolean'
          ? value
            ? 'yes'
            : 'no'
          : String(value)
      return `${DETAIL_LABELS[key] ?? humaniseKind(key)}: ${shown}`
    })
    .join(' · ')
}

function cohortLines(vs: VsSitting): string[] {
  if (vs.cohort_skipped) {
    return ['Not compared: too few finished candidates in this sitting for a fair comparison.']
  }
  const line = (label: string, value: number | undefined) =>
    value === undefined ? null : `${label}: ${ordinal(value)} percentile of the sitting`
  return [
    line('Pace', vs.pace_percentile),
    line('Answer-time spread', vs.spread_percentile),
    line('Score', vs.score_percentile),
  ].filter((l): l is string => l !== null)
}

function signalText(signal: InnocentSignal): string {
  const label = INNOCENT_LABELS[signal.kind] ?? humaniseKind(signal.kind)
  const parts: string[] = []
  if (signal.elapsed_s !== undefined) parts.push(`at ${formatElapsed(signal.elapsed_s)}`)
  if (signal.duration_s !== undefined) parts.push(`${signal.duration_s} s`)
  if (signal.note) parts.push(`"${signal.note}"`)
  return parts.length ? `${label}: ${parts.join(', ')}` : label
}

export default function CandidateDetail() {
  const { id = '' } = useParams()
  const queryClient = useQueryClient()
  const [target, setTarget] = useState<JumpTarget | null>(null)
  const nonce = useRef(0)

  const query = useQuery({
    queryKey: ['candidate', id],
    queryFn: () => api<Detail>(`/api/review/candidates/${encodeURIComponent(id)}`),
  })

  const shortlist = useMutation({
    mutationFn: () =>
      api<{ shortlisted: boolean }>(`/api/review/candidates/${encodeURIComponent(id)}/shortlist`, {
        method: 'POST',
      }),
    onSuccess: async () => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ['candidate', id] }),
        queryClient.invalidateQueries({ queryKey: ['queue'] }),
      ])
    },
  })

  function jump(seek: VideoSeek | null, label: string, flagId?: string) {
    nonce.current += 1
    setTarget(
      seek
        ? { kind: 'seek', segment: seek.segment, seekS: seek.seek_s, label, nonce: nonce.current }
        : { kind: 'none', label, nonce: nonce.current },
    )
    // Every jump is a video view the audit log must hold. It never blocks the jump.
    void api(`/api/review/candidates/${encodeURIComponent(id)}/video-view`, {
      method: 'POST',
      body: { flag_id: flagId ?? null },
    }).catch(() => undefined)
  }

  if (query.isPending) return <p role="status">Loading the candidate...</p>
  if (query.isError) {
    const notFound = query.error instanceof ApiError && query.error.code === 'candidate_not_found'
    return (
      <>
        <p role="alert" className="error">
          {notFound ? 'That candidate is not in the review queue.' : 'Could not load the candidate.'}
        </p>
        <p>
          <Link to="/review">Back to the queue</Link>
        </p>
      </>
    )
  }

  const d = query.data
  const aiShown = d.explanation.source === 'ai'
  const latestDecision = d.decisions[d.decisions.length - 1]

  return (
    <>
      <header className="detail-header">
        <h1>Candidate {d.candidate_id}</h1>
        <span className="badge">Rank {d.rank}</span>
        <span className={aiShown ? 'badge ai' : 'badge'}>
          {orderBasis(d.explanation.status, d.explanation.strength)}
        </span>
        {latestDecision && (
          <span className="badge">Decided: {OUTCOME_LABELS[latestDecision.outcome]}</span>
        )}
        <button
          type="button"
          className="secondary"
          disabled={shortlist.isPending}
          onClick={() => shortlist.mutate()}
        >
          {d.shortlisted ? 'Remove from shortlist' : 'Add to shortlist'}
        </button>
      </header>

      <div className="detail-grid">
        <div>
          <Section title="Summary">
            <p className="muted">{aiShown ? AI_LABEL : RULES_LABEL}</p>
            <p>{d.explanation.text}</p>
            {d.explanation.flags_support_each_other && (
              <p className="muted">
                Do the flags support each other: {d.explanation.flags_support_each_other}.
              </p>
            )}
          </Section>

          <Section title="Flags">
            {d.flags.length === 0 ? (
              <p>No flags.</p>
            ) : (
              <ul className="list">
                {d.flags.map((flag: FlagItem) => (
                  <li key={flag.id}>
                    <div>
                      <strong>{FLAG_LABELS[flag.kind] ?? humaniseKind(flag.kind)}</strong>
                      {' at '}
                      {formatElapsed(flag.elapsed_s)}
                      {flag.question_number !== null && `, question ${flag.question_number}`}
                    </div>
                    <div className="muted">{detailText(flag.detail)}</div>
                    <button
                      type="button"
                      className="secondary"
                      onClick={() =>
                        jump(flag.video_seek, `${flag.id} ${FLAG_LABELS[flag.kind] ?? flag.kind}`, flag.id)
                      }
                    >
                      Jump to video
                    </button>
                  </li>
                ))}
              </ul>
            )}
            <details>
              <summary>How the rule score of {d.rule_score} adds up</summary>
              <ul>
                {d.rule_breakdown.map((line) => (
                  <li key={line.label}>
                    {line.label}: {line.points}
                  </li>
                ))}
              </ul>
            </details>
          </Section>

          <Section title="Compared with the sitting">
            <ul>
              {cohortLines(d.vs_sitting).map((line) => (
                <li key={line}>{line}</li>
              ))}
            </ul>
            {d.history_source === 'synthetic' && (
              <p className="muted">
                The per-question history behind the "far faster than past candidates" flag is
                synthetic sample data, not Cytonn's.
              </p>
            )}
          </Section>

          <Section title="Context">
            <p className="muted">{CONTEXT_ONLY}</p>
            <ul>
              <li>Score: {d.score} correct</li>
              <li>Pace: {d.pace_s_per_q} s per question</li>
            </ul>
          </Section>

          <Section title="Things that may explain what you see">
            {d.innocent_signals.length === 0 ? (
              <p>None recorded.</p>
            ) : (
              <ul>
                {d.innocent_signals.map((signal) => (
                  <li key={signal.id}>{signalText(signal)}</li>
                ))}
              </ul>
            )}
            {d.self_report && (
              <p>
                Candidate's own report:{' '}
                {d.self_report.had_technical_issues
                  ? `technical problems${d.self_report.note ? `: "${d.self_report.note}"` : ''}`
                  : 'no technical problems'}
              </p>
            )}
          </Section>

          <Section title="Muted or silent microphone">
            <p className="muted">{CONTEXT_ONLY}</p>
            {d.mic_silence.length === 0 ? (
              <p>None of a minute or longer.</p>
            ) : (
              <ul className="list">
                {d.mic_silence.map((m) => (
                  <li key={m.id}>
                    <div>
                      {formatElapsed(m.start_s)} to {formatElapsed(m.end_s)} ({m.duration_s} s),
                      seen by {m.layers.join(' and ')}
                      {m.layers.includes('browser') && ' (the candidate saw the warning)'}
                    </div>
                    <button
                      type="button"
                      className="secondary"
                      onClick={() => jump(m.video_seek, `Microphone ${m.id}`)}
                    >
                      Jump to video
                    </button>
                  </li>
                ))}
              </ul>
            )}
          </Section>

          <Section title="Complaints">
            {d.complaints.length === 0 ? (
              <p>None filed.</p>
            ) : (
              <ul>
                {d.complaints.map((c) => (
                  <li key={c.id}>
                    {c.category} ({c.status}, {formatDateTime(c.created_at)}): {c.text}
                  </li>
                ))}
              </ul>
            )}
          </Section>

          <Section title="Earlier decisions">
            {d.decisions.length === 0 ? (
              <p>None yet.</p>
            ) : (
              <ul>
                {d.decisions.map((p) => (
                  <li key={p.decided_at}>
                    {OUTCOME_LABELS[p.outcome]} by {p.reviewer}, {formatDateTime(p.decided_at)}:{' '}
                    {p.reason}
                  </li>
                ))}
              </ul>
            )}
            <p className="muted">
              {RETENTION_NOTE}
              {d.video_purge_on && ` Video is due for deletion on ${formatDateTime(d.video_purge_on)}.`}
            </p>
          </Section>
        </div>

        <aside className="detail-side">
          <VideoPlayer segments={d.segments} target={target} deletedAt={d.video_deleted_at} />
          <DecisionForm sessionId={d.session_id} candidateId={d.candidate_id} />
        </aside>
      </div>
    </>
  )
}
