import { describe, expect, it } from 'vitest'
import { formatInviteCode, normaliseInviteCode } from '../src/lib/inviteCode'

describe('normaliseInviteCode()', () => {
  it('ignores case, dashes, spaces and underscores', () => {
    expect(normaliseInviteCode('abcd-efgh')).toBe('ABCDEFGH')
    expect(normaliseInviteCode('  ab cd_ef gh ')).toBe('ABCDEFGH')
  })

  it('reads the look-alikes O, I and L as 0, 1 and 1', () => {
    expect(normaliseInviteCode('O0O0-1I1L')).toBe('00001111')
  })

  it('leaves the long hex tokens from the first seed untouched', () => {
    const legacy = 'a3f9c1d2e4b5a6f7c8d9e0f1'
    expect(normaliseInviteCode(legacy)).toBe(legacy)
    expect(normaliseInviteCode(`  ${legacy}  `)).toBe(legacy)
  })

  it('leaves anything that is not a short code as typed (trimmed)', () => {
    expect(normaliseInviteCode(' ABCDEFGU ')).toBe('ABCDEFGU') // U is not in the alphabet
    expect(normaliseInviteCode('ABC')).toBe('ABC')
  })

  it('never folds non-ASCII text into a valid code', () => {
    expect(normaliseInviteCode('ssss')).toBe('ssss')
    expect(normaliseInviteCode('ßßßß')).toBe('ßßßß')
  })
})

describe('formatInviteCode()', () => {
  it('shows a short code as XXXX-XXXX', () => {
    expect(formatInviteCode('ABCDEFGH')).toBe('ABCD-EFGH')
  })

  it('returns anything else as it is', () => {
    expect(formatInviteCode('a3f9c1d2e4b5a6f7c8d9e0f1')).toBe('a3f9c1d2e4b5a6f7c8d9e0f1')
  })
})
