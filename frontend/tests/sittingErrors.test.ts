import { describe, expect, it } from 'vitest'
import { createMessage } from '../src/admin/sittingErrors'
import { ApiError } from '../src/lib/api'

describe('createMessage', () => {
  it('says nothing when there is no error', () => {
    expect(createMessage(null)).toBeNull()
  })

  it('names the sections that are too small for the sitting', () => {
    const error = new ApiError(409, 'section_too_small', {
      code: 'section_too_small',
      needed: 5,
      sections: [
        { section: 'verbal', available: 3 },
        { section: 'logical', available: 4 },
      ],
    })
    const message = createMessage(error) ?? ''
    expect(message).toContain('at least 5')
    expect(message).toContain('verbal has 3, logical has 4')
  })

  it('still explains a bank that is too small overall', () => {
    const error = new ApiError(409, 'question_bank_too_small', { available: 60 })
    expect(createMessage(error)).toBe('The question bank has only 60 questions.')
  })

  it('falls back for a code it does not know', () => {
    expect(createMessage(new ApiError(500, 'surprise', {}))).toBe('Could not create the sitting.')
  })
})
