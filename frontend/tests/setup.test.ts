import { describe, expect, it } from 'vitest'
import { setupSteps } from '../src/admin/setup'
import type { AdminSitting, QuestionBankSummary } from '../src/lib/adminTypes'

const bank = (cytonn: number, synthetic: number): QuestionBankSummary => ({
  total: cytonn + synthetic,
  cytonn,
  synthetic,
  by_section: [],
})

const sitting = (
  status: 'open' | 'closed',
  counts: { finished: number; in_progress: number; not_started: number },
  name = 'October sitting',
): AdminSitting => ({
  id: 1,
  name,
  opens_at: null,
  closes_at: null,
  duration_s: 1800,
  question_count: 12,
  status,
  counts,
})

const none = { finished: 0, in_progress: 0, not_started: 0 }
const byKey = (steps: ReturnType<typeof setupSteps>) =>
  Object.fromEntries(steps.map((step) => [step.key, step]))

describe('setup steps', () => {
  it('always lists the four steps in setup order', () => {
    expect(setupSteps(bank(0, 0), []).map((s) => s.key)).toEqual([
      'questions',
      'sitting',
      'invites',
      'close',
    ])
  })

  describe('questions', () => {
    it('asks for an import when the bank is empty', () => {
      const step = byKey(setupSteps(bank(0, 0), [])).questions
      expect(step.state).toBe('todo')
      expect(step.link?.to).toBe('/admin/questions')
    })

    it('says when only placeholders are in the bank', () => {
      const step = byKey(setupSteps(bank(0, 60), [])).questions
      expect(step.state).toBe('todo')
      expect(step.detail).toContain('Only placeholder questions')
      expect(step.detail).toContain('60')
    })

    it('asks for the placeholders to go once real questions are in', () => {
      const step = byKey(setupSteps(bank(40, 20), [])).questions
      expect(step.state).toBe('todo')
      expect(step.link?.label).toBe('Remove the placeholders')
    })

    it('is done with real questions only', () => {
      const step = byKey(setupSteps(bank(60, 0), [])).questions
      expect(step.state).toBe('done')
    })
  })

  describe('sitting, invitations and close', () => {
    it('waits on an open sitting', () => {
      const steps = byKey(setupSteps(bank(60, 0), [sitting('closed', none)]))
      expect(steps.sitting.state).toBe('todo')
      expect(steps.sitting.link?.to).toBe('#new-sitting')
      expect(steps.invites.state).toBe('later')
      expect(steps.close.state).toBe('later')
    })

    it('asks for invitation codes when the open sitting has none', () => {
      const steps = byKey(setupSteps(bank(60, 0), [sitting('open', none)]))
      expect(steps.sitting.state).toBe('done')
      expect(steps.sitting.detail).toContain('October sitting')
      expect(steps.invites.state).toBe('todo')
      expect(steps.invites.link?.to).toBe('/admin/invites')
    })

    it('counts invitations and finished candidates for the open sitting', () => {
      const steps = byKey(
        setupSteps(bank(60, 0), [
          sitting('closed', { finished: 9, in_progress: 0, not_started: 0 }, 'Old'),
          sitting('open', { finished: 14, in_progress: 2, not_started: 4 }),
        ]),
      )
      expect(steps.invites.state).toBe('done')
      expect(steps.invites.detail).toBe('20 invitations for this sitting.')
      expect(steps.close.state).toBe('later')
      expect(steps.close.detail).toContain('14 of 20 finished')
    })

    it('says one invitation in the singular', () => {
      const steps = byKey(
        setupSteps(bank(60, 0), [sitting('open', { finished: 0, in_progress: 0, not_started: 1 })]),
      )
      expect(steps.invites.detail).toBe('1 invitation for this sitting.')
    })

    it('offers to close only when everyone invited has finished', () => {
      const steps = byKey(
        setupSteps(bank(60, 0), [sitting('open', { finished: 5, in_progress: 0, not_started: 0 })]),
      )
      expect(steps.close.state).toBe('todo')
    })
  })
})
