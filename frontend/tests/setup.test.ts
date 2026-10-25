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
  blueprint: null,
  question_mode: 'bank',
  status,
  counts: { papers_pending: 0, papers_failed: 0, ...counts },
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
    it('needs no bank when the open sitting has its questions written by AI', () => {
      const ai = { ...sitting('open', none), question_mode: 'ai' as const }
      const step = byKey(setupSteps(bank(0, 0), [ai])).questions
      expect(step.state).toBe('done')
      expect(step.detail).toContain('no question bank is needed')
      expect(step.link).toBeUndefined()
    })

    it("is done once Cytonn's questions are loaded for a Cytonn sitting, whatever else is in the bank", () => {
      const cytonn = { ...sitting('open', none), question_mode: 'cytonn' as const }
      const loaded: QuestionBankSummary = {
        total: 1800,
        cytonn: 1740,
        synthetic: 60,
        by_section: [
          { section: 'numerical', count: 583, cytonn: 563, synthetic: 20 },
          { section: 'verbal', count: 570, cytonn: 550, synthetic: 20 },
          { section: 'logical', count: 270, cytonn: 250, synthetic: 20 },
          { section: 'ai competence', count: 26, cytonn: 26, synthetic: 0 },
        ],
      }
      const step = byKey(setupSteps(loaded, [cytonn])).questions
      expect(step.state).toBe('done')
      expect(step.detail).toBe("Cytonn's 1740 questions, in 4 sections.")
    })

    it("asks for Cytonn's questions to be loaded when a Cytonn sitting has none to draw on", () => {
      const cytonn = { ...sitting('open', none), question_mode: 'cytonn' as const }
      const step = byKey(setupSteps(bank(0, 60), [cytonn])).questions
      expect(step.state).toBe('todo')
      expect(step.detail).toContain('none are loaded yet')
    })

    it('still asks for the bank when the open sitting draws from it', () => {
      expect(byKey(setupSteps(bank(0, 0), [sitting('open', none)])).questions.state).toBe('todo')
    })

    it('asks for an import when the bank is empty', () => {
      const step = byKey(setupSteps(bank(0, 0), [])).questions
      expect(step.state).toBe('todo')
      expect(step.link?.to).toBe('/admin/questions')
    })

    it('says when only practice questions are in the bank', () => {
      const step = byKey(setupSteps(bank(0, 60), [])).questions
      expect(step.state).toBe('todo')
      expect(step.detail).toContain('Only practice questions')
      expect(step.detail).toContain('60')
    })

    it('asks for the practice questions to go once real questions are in', () => {
      const step = byKey(setupSteps(bank(40, 20), [])).questions
      expect(step.state).toBe('todo')
      expect(step.link?.label).toBe('Remove the practice questions')
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
