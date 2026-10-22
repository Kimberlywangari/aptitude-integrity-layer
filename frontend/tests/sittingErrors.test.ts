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
      sections: [
        { section: 'verbal', available: 3, needed: 5 },
        { section: 'logical', available: 4, needed: 6 },
      ],
    })
    const message = createMessage(error) ?? ''
    expect(message).toContain('verbal has 3 (5 asked for)')
    expect(message).toContain('logical has 4 (6 asked for)')
  })

  it('names a section the bank does not have', () => {
    const error = new ApiError(422, 'unknown_section', { code: 'unknown_section', sections: ['astrology'] })
    expect(createMessage(error)).toContain('astrology')
  })

  it('still explains a bank that is too small overall', () => {
    const error = new ApiError(409, 'question_bank_too_small', { available: 60 })
    expect(createMessage(error)).toBe('The question bank has only 60 questions.')
  })

  it('falls back for a code it does not know', () => {
    expect(createMessage(new ApiError(500, 'surprise', {}))).toBe('Could not create the sitting.')
  })
})
