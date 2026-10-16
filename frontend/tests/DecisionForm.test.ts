import { QueryClient, VueQueryPlugin } from '@tanstack/vue-query'
import { flushPromises, mount } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { resetMock, setMockLatency } from '../src/lib/mock'
import { clearStaff, saveStaff } from '../src/lib/staffSession'
import DecisionForm from '../src/reviewer/DecisionForm.vue'

vi.mock('../src/lib/api', async (importOriginal) =>
  (await import('./helpers/mockedApi')).withMockedApi(await importOriginal()),
)

function renderForm() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return mount(DecisionForm, {
    props: { sessionId: 'sess-cand-007', candidateId: 'cand-007' },
    global: { plugins: [[VueQueryPlugin, { queryClient }]] },
    attachTo: document.body,
  })
}

type Form = ReturnType<typeof renderForm>
const submit = (w: Form) => w.get('button[type=submit]').element as HTMLButtonElement
const outcome = (w: Form, label: string) =>
  w.findAll('label.option').find((l) => l.text().includes(label))!.get('input')
const reason = (w: Form) => w.get('#reason')
const confirm = (w: Form) => w.get('.check input')

describe('DecisionForm', () => {
  beforeEach(() => {
    setMockLatency(0)
    resetMock()
    saveStaff({ token: 'mock-reviewer:r@example.com', email: 'r@example.com', role: 'reviewer' })
  })

  afterEach(() => {
    document.body.innerHTML = ''
    clearStaff()
  })

  it('stays disabled until an outcome, a 20-character reason and the confirmation are all given', async () => {
    const w = renderForm()
    expect(submit(w).disabled).toBe(true)

    await outcome(w, 'No concern').setValue(true)
    expect(submit(w).disabled).toBe(true)

    await reason(w).setValue('too short')
    await confirm(w).setValue(true)
    expect(submit(w).disabled).toBe(true)

    await reason(w).setValue('Pace is steady and the video shows nothing unusual.')
    expect(submit(w).disabled).toBe(false)
  })

  it('does not count surrounding spaces towards the reason length', async () => {
    const w = renderForm()
    await outcome(w, 'Concern noted').setValue(true)
    await confirm(w).setValue(true)
    await reason(w).setValue(`   ${'x'.repeat(10)}${' '.repeat(30)}`)
    expect(submit(w).disabled).toBe(true)
  })

  it('saves the decision and clears the form', async () => {
    const w = renderForm()
    await outcome(w, 'Refer for follow-up').setValue(true)
    await reason(w).setValue('Copy attempt then a long hold; worth a second look.')
    await confirm(w).setValue(true)
    await w.get('form').trigger('submit')
    await flushPromises()

    expect(w.get('[role=status]').text()).toBe('Decision recorded.')
    expect((reason(w).element as HTMLTextAreaElement).value).toBe('')
    expect(submit(w).disabled).toBe(true)
  })
})
