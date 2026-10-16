import { describe, expect, it } from 'vitest'
import { formatElapsed, humaniseKind, ordinal } from '../src/lib/format'

describe('ordinal()', () => {
  it('uses st, nd, rd and th correctly', () => {
    expect([1, 2, 3, 4, 8, 21, 22, 23, 91, 102].map(ordinal)).toEqual([
      '1st',
      '2nd',
      '3rd',
      '4th',
      '8th',
      '21st',
      '22nd',
      '23rd',
      '91st',
      '102nd',
    ])
  })

  it('uses th for the teens', () => {
    expect([11, 12, 13, 111, 112].map(ordinal)).toEqual(['11th', '12th', '13th', '111th', '112th'])
  })
})

describe('formatElapsed()', () => {
  it('writes m:ss, and h:mm:ss from an hour on', () => {
    expect(formatElapsed(0)).toBe('0:00')
    expect(formatElapsed(305)).toBe('5:05')
    expect(formatElapsed(3725)).toBe('1:02:05')
  })

  it('never goes below zero', () => {
    expect(formatElapsed(-4)).toBe('0:00')
  })
})

describe('humaniseKind()', () => {
  it('makes an unknown flag kind readable', () => {
    expect(humaniseKind('NEW_FLAG_KIND')).toBe('New flag kind')
  })
})
