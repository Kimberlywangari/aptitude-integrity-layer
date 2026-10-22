import { ApiError } from '../lib/api'

const CREATE_ERRORS: Record<string, string> = {
  name_required: 'Give the sitting a name.',
  name_too_long: 'That name is too long. Use 100 characters or fewer.',
  name_taken: 'A sitting with that name already exists.',
  invalid_duration: 'The duration must be at least one minute.',
  invalid_question_count: 'The sitting needs at least one question.',
  invalid_window: 'It must close after it opens.',
}

interface ShortSection {
  section: string
  available: number
}

function shortSections(value: unknown): ShortSection[] {
  return Array.isArray(value) ? (value as ShortSection[]) : []
}

export function createMessage(error: unknown): string | null {
  if (!error) return null
  if (error instanceof ApiError) {
    if (error.code === 'question_bank_too_small') {
      return `The question bank has only ${String(error.body.available ?? 'a few')} questions.`
    }
    if (error.code === 'section_too_small') {
      const short = shortSections(error.body.sections)
        .map((s) => `${s.section} has ${s.available}`)
        .join(', ')
      return `The questions are spread over the sections, so each needs at least ${String(error.body.needed)} for a sitting this size: ${short}. Ask for fewer questions, or load more.`
    }
    return CREATE_ERRORS[error.code] ?? 'Could not create the sitting.'
  }
  return 'Could not create the sitting.'
}
