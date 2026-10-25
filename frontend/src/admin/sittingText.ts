// How a sitting is described in words, on the list of sittings and on a sitting's own page.

import type { AdminSitting } from '../lib/adminTypes'
import { formatDateTime } from '../lib/format'

const MODE_LABEL: Record<string, string> = {
  cytonn: "Cytonn's questions: ",
  ai: 'written by AI: ',
  practice: 'practice questions: ',
  bank: '',
}

/** What the paper is made of: "Cytonn's questions: numerical 2, verbal 2". */
export const paperOf = (s: AdminSitting) =>
  s.blueprint
    ? `${MODE_LABEL[s.question_mode] ?? ''}${Object.entries(s.blueprint)
        .map(([section, n]) => `${section} ${n}`)
        .join(', ')}`
    : 'spread evenly'

/** Everyone invited, whether or not they have used their code. */
export const totalOf = (s: AdminSitting) =>
  s.counts.finished + s.counts.in_progress + s.counts.not_started

export interface SittingState {
  label: string
  pill: string
  title?: string
}

// What a sitting is right now, in a word: "Open" only when a candidate could start it. A sitting
// whose opening time is still ahead, or whose closing time has passed, is not, whatever its status.
export function stateOf(s: AdminSitting): SittingState {
  if (s.status === 'closed') return { label: 'Closed', pill: 'plain' }
  const now = Date.now()
  if (s.opens_at && now < Date.parse(s.opens_at)) {
    return {
      label: 'Not open yet',
      pill: 'moderate',
      title: `Candidates cannot start until ${formatDateTime(s.opens_at)}`,
    }
  }
  if (s.closes_at && now >= Date.parse(s.closes_at)) {
    return {
      label: 'Time ended',
      pill: 'plain',
      title: `The window closed ${formatDateTime(s.closes_at)}; close the sitting to finish it`,
    }
  }
  return { label: 'Open', pill: 'ok' }
}

/** "Always open", or "Mon 20 Oct, 09:00 to Mon 20 Oct, 11:00". */
export const windowOf = (s: AdminSitting) =>
  s.opens_at || s.closes_at
    ? `${formatDateTime(s.opens_at)} to ${formatDateTime(s.closes_at)}`
    : 'Always open'
