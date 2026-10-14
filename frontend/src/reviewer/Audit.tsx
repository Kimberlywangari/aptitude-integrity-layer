import { useQuery } from '@tanstack/react-query'
import { api } from '../lib/api'
import { formatDateTime } from '../lib/format'
import type { AuditEntry } from '../lib/reviewTypes'

const ACTION_LABELS: Record<AuditEntry['action'], string> = {
  login: 'Sign-in',
  decision: 'Decision or shortlist',
  video_view: 'Video viewed',
  video_purged: 'Video deleted',
  admin: 'Setup action',
}

export default function Audit() {
  const audit = useQuery({
    queryKey: ['audit'],
    queryFn: () => api<{ entries: AuditEntry[] }>('/api/review/audit'),
  })

  if (audit.isPending) return <p role="status">Loading the audit log...</p>
  if (audit.isError) {
    return (
      <p role="alert" className="error">
        Could not load the audit log.
      </p>
    )
  }

  return (
    <>
      <h1>Audit log</h1>
      <p className="muted">
        Sign-ins, decisions, video views, setup actions and deletions, newest first.
      </p>
      <div className="table-wrap">
        <table className="table">
          <thead>
            <tr>
              <th>When</th>
              <th>Who</th>
              <th>Action</th>
              <th>Candidate</th>
              <th>Detail</th>
            </tr>
          </thead>
          <tbody>
            {audit.data.entries.map((entry) => (
              <tr key={entry.id}>
                <td>{formatDateTime(entry.ts)}</td>
                <td>{entry.reviewer}</td>
                <td>{ACTION_LABELS[entry.action]}</td>
                <td>{entry.candidate_id ?? ''}</td>
                <td>{entry.detail}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </>
  )
}
