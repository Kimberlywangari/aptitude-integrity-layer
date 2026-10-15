import type { AdminSitting, QuestionBankSummary } from '../lib/adminTypes'

export type StepState = 'done' | 'todo' | 'later'

export interface SetupStep {
  key: 'questions' | 'sitting' | 'invites' | 'close'
  title: string
  state: StepState
  detail: string
  link?: { to: string; label: string }
}

/**
 * Where the recruiter is in the setup order (questions, sitting, invitations, close), worked out
 * from the question bank and the sittings list the Sittings page already loads. Nothing extra is
 * fetched, and nothing here decides anything: it only says what the numbers show.
 */
export function setupSteps(bank: QuestionBankSummary, sittings: AdminSitting[]): SetupStep[] {
  const open = sittings.find((sitting) => sitting.status === 'open')
  const counts = open?.counts
  const invited = counts ? counts.finished + counts.in_progress + counts.not_started : 0

  const questions: SetupStep = (() => {
    const title = 'Questions'
    const link = '/admin/questions'
    if (bank.total === 0) {
      return {
        key: 'questions',
        title,
        state: 'todo',
        detail: 'The question bank is empty.',
        link: { to: link, label: 'Import questions' },
      }
    }
    if (bank.cytonn === 0) {
      return {
        key: 'questions',
        title,
        state: 'todo',
        detail: `Only placeholder questions so far (${bank.synthetic}).`,
        link: { to: link, label: 'Import the real questions' },
      }
    }
    if (bank.synthetic > 0) {
      return {
        key: 'questions',
        title,
        state: 'todo',
        detail: `${bank.cytonn} real questions, and ${bank.synthetic} placeholders still in the bank.`,
        link: { to: link, label: 'Remove the placeholders' },
      }
    }
    return {
      key: 'questions',
      title,
      state: 'done',
      detail: `${bank.cytonn} questions from Cytonn.`,
      link: { to: link, label: 'Open questions' },
    }
  })()

  const sitting: SetupStep = open
    ? { key: 'sitting', title: 'Sitting', state: 'done', detail: `"${open.name}" is open.` }
    : {
        key: 'sitting',
        title: 'Sitting',
        state: 'todo',
        detail: 'No sitting is open.',
        link: { to: '#new-sitting', label: 'Create one below' },
      }

  const invites: SetupStep = (() => {
    const title = 'Invitations'
    if (!open) {
      return { key: 'invites', title, state: 'later', detail: 'Needs an open sitting first.' }
    }
    if (invited > 0) {
      return {
        key: 'invites',
        title,
        state: 'done',
        detail: `${invited} invitation${invited === 1 ? '' : 's'} for this sitting.`,
        link: { to: '/admin/invites', label: 'Open invites' },
      }
    }
    return {
      key: 'invites',
      title,
      state: 'todo',
      detail: 'No invitation codes yet.',
      link: { to: '/admin/invites', label: 'Generate codes' },
    }
  })()

  const close: SetupStep = (() => {
    const title = 'Close'
    if (!open || !counts) {
      return { key: 'close', title, state: 'later', detail: 'Nothing to close.' }
    }
    if (invited > 0 && counts.finished === invited) {
      return {
        key: 'close',
        title,
        state: 'todo',
        detail: 'Everyone has finished. Close the sitting so flags can be built.',
      }
    }
    return {
      key: 'close',
      title,
      state: 'later',
      detail:
        invited > 0
          ? `${counts.finished} of ${invited} finished. Close the sitting when everyone is done.`
          : 'Close the sitting once candidates have finished.',
    }
  })()

  return [questions, sitting, invites, close]
}
