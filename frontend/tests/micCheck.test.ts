import { describe, expect, it } from 'vitest'
import { INITIAL_MIC_CHECK, MIC_CHECK, stepMicCheck } from '../src/lib/micCheck'
import type { MicCheckState } from '../src/lib/micCheck'

function run(levels: number[], dtMs = 100): MicCheckState {
  return levels.reduce((state, rms) => stepMicCheck(state, rms, dtMs), INITIAL_MIC_CHECK)
}

describe('stepMicCheck()', () => {
  const loud = MIC_CHECK.speechRms * 5
  const quiet = MIC_CHECK.speechRms / 5

  it('passes after one second above the threshold', () => {
    expect(run(Array(9).fill(loud)).result).toBe('listening')
    expect(run(Array(10).fill(loud)).result).toBe('passed')
  })

  it('counts the gaps between words: pauses do not restart the second', () => {
    const speech = Array.from({ length: 10 }, () => [loud, loud, quiet]).flat() // 3 ticks a word
    expect(run(speech).result).toBe('passed')
  })

  it('fails after ten seconds without enough sound', () => {
    expect(run(Array(99).fill(quiet)).result).toBe('listening')
    expect(run(Array(100).fill(quiet)).result).toBe('failed')
  })

  it('fails when only a short blip was heard', () => {
    expect(run([...Array(5).fill(loud), ...Array(95).fill(quiet)]).result).toBe('failed')
  })

  it('can pass late, inside the ten seconds', () => {
    expect(run([...Array(80).fill(quiet), ...Array(10).fill(loud)]).result).toBe('passed')
  })

  it('keeps a finished result', () => {
    const passed = run(Array(10).fill(loud))
    expect(stepMicCheck(passed, 0, 20_000)).toBe(passed)
  })
})
