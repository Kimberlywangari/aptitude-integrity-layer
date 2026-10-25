import { ApiError } from '../lib/api'

const CREATE_ERRORS: Record<string, string> = {
  name_required: 'Give the sitting a name.',
  name_too_long: 'That name is too long. Use 100 characters or fewer.',
  name_taken: 'A sitting with that name already exists.',
  invalid_question_count: 'Ask for at least one question from at least one section.',
  invalid_window: 'It must close after it opens.',
  too_many_questions: 'That is too many questions. Ask for fewer.',
  question_writer_unavailable:
    'The question writer cannot be reached, so an AI sitting cannot be made yet.',
}

interface ShortSection {
  section: string
  available: number
  needed: number
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
        .map((s) => `${s.section} has ${s.available} (${s.needed} asked for)`)
        .join(', ')
      return `Not enough questions in: ${short}. Ask for fewer, or load more first.`
    }
    if (error.code === 'question_writer_unavailable') {
      const why = typeof error.body.detail === 'string' ? ` ${error.body.detail}` : ''
      return `${CREATE_ERRORS.question_writer_unavailable}${why}`
    }
    if (error.code === 'too_many_questions') {
      const each = error.body.max_per_category
      const all = error.body.max_total
      if (typeof each === 'number') return `At most ${each} questions from one category.`
      if (typeof all === 'number') return `At most ${all} questions in one paper.`
    }
    if (error.code === 'unknown_section') {
      const names = Array.isArray(error.body.sections) ? error.body.sections.join(', ') : ''
      return `The question bank has no section called: ${names}.`
    }
    return CREATE_ERRORS[error.code] ?? 'Could not create the sitting.'
  }
  return 'Could not create the sitting.'
}
