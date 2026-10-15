import { describe, expect, it } from 'vitest'
import { waitPhrase } from '../src/lib/wait'

describe('waitPhrase', () => {
  it('rounds up to whole minutes and never says zero', () => {
    expect(waitPhrase(0)).toBe('about 1 minute')
    expect(waitPhrase(1)).toBe('about 1 minute')
    expect(waitPhrase(60)).toBe('about 1 minute')
    expect(waitPhrase(61)).toBe('about 2 minutes')
    expect(waitPhrase(600)).toBe('about 10 minutes')
  })
})
