import type { Invite } from './adminTypes'

function cell(value: string): string {
  return /[",\r\n]/.test(value) ? `"${value.replace(/"/g, '""')}"` : value
}

/** The columns backend/scripts/seed_synthetic.py writes to data/invites.csv, plus the sitting the
 *  codes are for when it is named, and the name and email when the invitations were made for people
 *  (the fallback if an email does not arrive: send the code and link by hand). */
export function invitesToCsv(invites: Invite[], baseUrl: string, sitting?: string): string {
  const base = baseUrl.replace(/\/+$/, '')
  const people = invites.some((i) => i.email)
  const rows = invites.map((i) => [
    i.candidate_id,
    ...(people ? [i.name ?? '', i.email ?? ''] : []),
    i.code,
    `${base}/?t=${i.code}`,
    ...(sitting === undefined ? [] : [sitting]),
  ])
  const header = [
    'candidate_id',
    ...(people ? ['name', 'email'] : []),
    'token',
    'url',
    ...(sitting === undefined ? [] : ['sitting']),
  ]
  return [header, ...rows].map((r) => r.map(cell).join(',')).join('\r\n')
}
