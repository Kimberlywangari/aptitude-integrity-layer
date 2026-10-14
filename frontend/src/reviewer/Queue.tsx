import { useQuery } from '@tanstack/react-query'
import { Link, useSearchParams } from 'react-router-dom'
import { api } from '../lib/api'
import { humaniseKind } from '../lib/format'
import type { QueueItem, QueueResponse } from '../lib/reviewTypes'
import { FLAG_LABELS, OUTCOME_LABELS, orderBasis } from './copy'

function Row({ item }: { item: QueueItem }) {
  const kinds = [...new Set(item.flag_kinds)]
  return (
    <tr>
      <td>{item.rank}</td>
      <td className="nowrap">
        <Link to={`/review/candidates/${item.candidate_id}`}>{item.candidate_id}</Link>
      </td>
      <td>
        {kinds.map((kind) => (
          <span key={kind} className="chip">
            {FLAG_LABELS[kind] ?? humaniseKind(kind)}
          </span>
        ))}
      </td>
      <td>
        <span className={item.ai_strength !== null ? 'badge ai' : 'badge'}>
          {orderBasis(item.ai_status, item.ai_strength)}
        </span>
      </td>
      <td>{item.rule_score}</td>
      <td className="nowrap">{item.decision ? OUTCOME_LABELS[item.decision] : 'Not decided'}</td>
      <td>{item.shortlisted ? 'Shortlisted' : ''}</td>
    </tr>
  )
}

function Table({ items }: { items: QueueItem[] }) {
  return (
    <div className="table-wrap">
      <table className="table">
        <thead>
          <tr>
            <th>Rank</th>
            <th>Candidate</th>
            <th>Flags</th>
            <th>Order set by</th>
            <th>Rule score</th>
            <th>Decision</th>
            <th>Shortlist</th>
          </tr>
        </thead>
        <tbody>
          {items.map((item) => (
            <Row key={item.candidate_id} item={item} />
          ))}
        </tbody>
      </table>
    </div>
  )
}

export default function Queue() {
  const [params, setParams] = useSearchParams()
  const sitting = params.get('sitting')

  const queue = useQuery({
    queryKey: ['queue', sitting],
    queryFn: () =>
      api<QueueResponse>(
        `/api/review/queue${sitting ? `?sitting=${encodeURIComponent(sitting)}` : ''}`,
      ),
  })

  if (queue.isPending) return <p role="status">Loading the queue...</p>
  if (queue.isError) {
    return (
      <p role="alert" className="error">
        Could not load the queue. <button onClick={() => void queue.refetch()}>Try again</button>
      </p>
    )
  }

  const { sittings, sitting_id, items } = queue.data
  const main = items.filter((i) => !i.logging_only)
  const lowLane = items.filter((i) => i.logging_only)

  return (
    <>
      <h1>Review queue</h1>
      <label htmlFor="sitting">Sitting</label>
      <select
        id="sitting"
        value={sitting_id}
        onChange={(e) => setParams({ sitting: e.target.value })}
      >
        {sittings.map((s) => (
          <option key={s.id} value={s.id}>
            {s.name}
          </option>
        ))}
      </select>

      <p className="muted">
        Every flagged candidate is here. The order is a suggestion to help you start; nobody is set
        aside, and the AI never decides anything.
      </p>

      {items.length === 0 ? (
        <p>
          No flagged candidates in this sitting yet. Flags appear once the sitting is closed and
          the jobs have run.
        </p>
      ) : (
        <>
          <Table items={main} />
          {lowLane.length > 0 && (
            <section aria-labelledby="low-lane">
              <h2 id="low-lane">Logging problems only (low priority)</h2>
              <p className="muted">
                A gap in the page's heartbeat that a dropped connection or reload does not
                explain. These sit at the bottom, but a person should still look at them.
              </p>
              <Table items={lowLane} />
            </section>
          )}
        </>
      )}
    </>
  )
}
