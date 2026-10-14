import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { resetMock, setMockLatency } from '../src/lib/mock'
import { saveStaff, clearStaff } from '../src/lib/staffSession'
import DecisionForm from '../src/reviewer/DecisionForm'

vi.mock('../src/lib/api', async (importOriginal) =>
  (await import('./helpers/mockedApi')).withMockedApi(await importOriginal()),
)

function renderForm() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={client}>
      <DecisionForm sessionId="sess-cand-007" candidateId="cand-007" />
    </QueryClientProvider>,
  )
}

const submit = () => screen.getByRole('button', { name: 'Record decision' }) as HTMLButtonElement

describe('DecisionForm', () => {
  beforeEach(() => {
    setMockLatency(0)
    resetMock()
    saveStaff({ token: 'mock-reviewer:r@example.com', email: 'r@example.com', role: 'reviewer' })
  })

  afterEach(() => {
    cleanup()
    clearStaff()
  })

  it('stays disabled until an outcome, a 20-character reason and the confirmation are all given', () => {
    renderForm()
    expect(submit().disabled).toBe(true)

    fireEvent.click(screen.getByLabelText('No concern'))
    expect(submit().disabled).toBe(true)

    fireEvent.change(screen.getByLabelText(/Reason/), { target: { value: 'too short' } })
    fireEvent.click(screen.getByLabelText(/I have looked at the evidence/))
    expect(submit().disabled).toBe(true)

    fireEvent.change(screen.getByLabelText(/Reason/), {
      target: { value: 'Pace is steady and the video shows nothing unusual.' },
    })
    expect(submit().disabled).toBe(false)
  })

  it('does not count surrounding spaces towards the reason length', () => {
    renderForm()
    fireEvent.click(screen.getByLabelText('Concern noted'))
    fireEvent.click(screen.getByLabelText(/I have looked at the evidence/))
    fireEvent.change(screen.getByLabelText(/Reason/), {
      target: { value: `   ${'x'.repeat(10)}${' '.repeat(30)}` },
    })
    expect(submit().disabled).toBe(true)
  })

  it('saves the decision and clears the form', async () => {
    renderForm()
    fireEvent.click(screen.getByLabelText('Refer for follow-up'))
    fireEvent.change(screen.getByLabelText(/Reason/), {
      target: { value: 'Copy attempt then a long hold; worth a second look.' },
    })
    fireEvent.click(screen.getByLabelText(/I have looked at the evidence/))
    fireEvent.click(submit())

    await waitFor(() => expect(screen.getByRole('status').textContent).toBe('Decision recorded.'))
    expect((screen.getByLabelText(/Reason/) as HTMLTextAreaElement).value).toBe('')
    expect(submit().disabled).toBe(true)
  })
})
