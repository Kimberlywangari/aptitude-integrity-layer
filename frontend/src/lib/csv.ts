import type { Invite } from './adminTypes'

function cell(value: string): string {
  return /[",\r\n]/.test(value) ? `"${value.replace(/"/g, '""')}"` : value
}

/** Same columns as backend/scripts/seed_synthetic.py writes to data/invites.csv. */
export function invitesToCsv(invites: Invite[], baseUrl: string): string {
  const base = baseUrl.replace(/\/+$/, '')
  const rows = invites.map((i) => [i.candidate_id, i.code, `${base}/?t=${i.code}`])
  return [['candidate_id', 'token', 'url'], ...rows].map((r) => r.map(cell).join(',')).join('\r\n')
}
