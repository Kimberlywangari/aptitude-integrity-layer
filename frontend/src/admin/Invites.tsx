import { useMutation } from '@tanstack/react-query'
import { useState } from 'react'
import type { FormEvent } from 'react'
import { api } from '../lib/api'
import type { Invite, InvitesResponse } from '../lib/adminTypes'
import { invitesToCsv } from '../lib/csv'
import { formatInviteCode } from '../lib/inviteCode'

const MAX_INVITES = 500

function download(filename: string, text: string): void {
  const url = URL.createObjectURL(new Blob([text], { type: 'text/csv;charset=utf-8' }))
  const link = document.createElement('a')
  link.href = url
  link.download = filename
  link.click()
  URL.revokeObjectURL(url)
}

export default function Invites() {
  const [count, setCount] = useState(20)
  const [invites, setInvites] = useState<Invite[] | null>(null)

  const generate = useMutation({
    mutationFn: (n: number) =>
      api<InvitesResponse>('/api/admin/invites', { method: 'POST', body: { count: n } }),
    onSuccess: (data) => setInvites(data.invites),
  })

  function submit(event: FormEvent) {
    event.preventDefault()
    generate.mutate(Math.round(count))
  }

  const valid = Number.isFinite(count) && count >= 1 && count <= MAX_INVITES

  return (
    <>
      <h1>Invitations</h1>
      <p>
        Each candidate gets one personal code. Send them the same Safe Exam Browser file you send
        everyone, and their own code; they type it on the first screen. Candidate IDs are opaque:
        keep the list of who holds which ID on your side, it is never stored here.
      </p>

      <form className="panel" onSubmit={submit}>
        <label htmlFor="count">How many new codes (1 to {MAX_INVITES})</label>
        <input
          id="count"
          type="number"
          min={1}
          max={MAX_INVITES}
          value={count}
          onChange={(e) => setCount(Number(e.target.value))}
        />
        <button type="submit" disabled={!valid || generate.isPending}>
          {generate.isPending ? 'Generating...' : 'Generate codes'}
        </button>
        {generate.isError && (
          <p role="alert" className="error">
            Could not generate the codes.
          </p>
        )}
      </form>

      {invites && (
        <section className="panel">
          <h2>{invites.length} new codes</h2>
          <p role="status" className="banner">
            These are shown once. The server keeps only a hash, so download the list now.
          </p>
          <div className="actions">
            <button
              type="button"
              onClick={() =>
                download(
                  'invites.csv',
                  invitesToCsv(
                    invites.map((i) => ({ ...i, code: formatInviteCode(i.code) })),
                    window.location.origin,
                  ),
                )
              }
            >
              Download CSV
            </button>
            <button type="button" className="secondary" onClick={() => setInvites(null)}>
              Clear this list
            </button>
          </div>
          <div className="table-wrap">
            <table className="table">
              <thead>
                <tr>
                  <th>Candidate ID</th>
                  <th>Code</th>
                </tr>
              </thead>
              <tbody>
                {invites.map((i) => (
                  <tr key={i.candidate_id}>
                    <td>{i.candidate_id}</td>
                    <td className="mono">{formatInviteCode(i.code)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      )}
    </>
  )
}
