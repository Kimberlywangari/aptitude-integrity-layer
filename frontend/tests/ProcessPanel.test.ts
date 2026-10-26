import { flushPromises } from '@vue/test-utils'
import type { VueWrapper } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { api, ApiError } from '../src/lib/api'
import { resetMock, setMockLatency } from './mock'
import { clearStaff, saveStaff } from '../src/lib/staffSession'
import { clearQueryClient } from '../src/staff/queryClient'
import { renderApp, until } from './helpers/render'

vi.mock('../src/lib/api', async (importOriginal) =>
  (await import('./helpers/mockedApi')).withMockedApi(await importOriginal()),
)

const norm = (text: string) => text.replace(/\s+/g, ' ').trim()
const untilText = (w: VueWrapper, text: string, timeoutMs = 3000) =>
  until(() => norm(w.text()).includes(text), timeoutMs)
const button = (w: VueWrapper, name: string) => w.findAll('button').find((b) => b.text().trim() === name)

async function renderAt(path: string) {
  const { wrapper } = await renderApp(path)
  await flushPromises()
  return wrapper
}

// the mock's sitting 1 is open; sitting 2 is closed
const OPEN = '/admin/sittings/1'
const CLOSED = '/admin/sittings/2'

describe('Prepare for review (the Process sitting button)', () => {
  beforeEach(() => {
    setMockLatency(0)
    resetMock()
    clearStaff()
    clearQueryClient()
    saveStaff({ token: 'mock-admin:admin@example.com', email: 'admin@example.com', role: 'admin' })
  })

  afterEach(() => {
    clearStaff()
    clearQueryClient()
    document.body.innerHTML = ''
  })

  it('is on the sitting page, and says what it does and that nothing is decided by it', async () => {
    const w = await renderAt(CLOSED)
    await untilText(w, 'Prepare for review')
    const text = norm(w.text())
    expect(text).toContain('Running it again is safe')
    expect(text).toContain('The order comes from the rules alone; no AI is used.')
    expect(button(w, 'Process sitting')).toBeDefined()
  })

  it('cannot be pressed while the sitting is still open, and says why', async () => {
    const w = await renderAt(OPEN)
    await untilText(w, 'Prepare for review')
    expect(norm(w.text())).toContain('Close the sitting first')
    expect(button(w, 'Process sitting')!.attributes('disabled')).toBeDefined()
  })

  it('shows the run and then its steps, and offers to process again', async () => {
    const w = await renderAt(CLOSED)
    await untilText(w, 'Prepare for review')
    await button(w, 'Process sitting')!.trigger('click')

    await untilText(w, 'Working since')
    expect(button(w, 'Working...')!.attributes('disabled')).toBeDefined()

    // the page asks again by itself every two seconds until the run is over
    await untilText(w, 'The reviewers\' queue is up to date', 6000)
    const text = norm(w.text())
    for (const label of ['compute flags', 'assemble video', 'scan audio', 'build packets', 'rank']) {
      expect(text).toContain(label)
    }
    expect(text).toContain('6 packets')
    expect(button(w, 'Process again')).toBeDefined()
  })

  it('remembers the last run after the page is opened again', async () => {
    const w = await renderAt(CLOSED)
    await untilText(w, 'Prepare for review')
    await button(w, 'Process sitting')!.trigger('click')
    await untilText(w, 'The reviewers\' queue is up to date', 6000)
    w.unmount()
    clearQueryClient()

    const again = await renderAt(CLOSED)
    await untilText(again, 'Prepare for review')
    await until(() => button(again, 'Process again') !== undefined)
    expect(norm(again.text())).toContain('Finished')
  })

  it('says to close the sitting first if the server refuses because it is open', async () => {
    const w = await renderAt(CLOSED)
    await untilText(w, 'Prepare for review')
    vi.mocked(api).mockImplementationOnce(() => Promise.reject(new ApiError(409, 'sitting_not_closed', {})))
    await button(w, 'Process sitting')!.trigger('click')
    await untilText(w, 'Close the sitting first.')
  })

  it('shows a failed run in words and keeps the button for another try', async () => {
    const real = vi.mocked(api).getMockImplementation()!
    vi.mocked(api).mockImplementation(async (path: string, options?: { method?: string }) =>
      path.endsWith('/sittings/2/process') && options?.method !== 'POST'
        ? {
            state: 'failed',
            provider: 'claude',
            model: 'claude-test',
            steps: [
              { label: 'compute flags', seconds: 0.2, note: '3 flags on 1/4 sessions, cohort applied' },
            ],
            error: 'The AI step could not start: no Anthropic key is set',
            started_at: '2026-10-26T10:00:00Z',
            finished_at: '2026-10-26T10:00:02Z',
            last_ranked_at: null,
          }
        : real(path, options),
    )
    try {
      const w = await renderAt(CLOSED)
      await untilText(w, 'no Anthropic key is set')
      const text = norm(w.text())
      expect(text).toContain('What was finished is kept; you can run it again.')
      expect(text).toContain('Claude (claude-test)')
      expect(text).toContain('compute flags')
      expect(button(w, 'Process again')!.attributes('disabled')).toBeUndefined()
    } finally {
      vi.mocked(api).mockImplementation(real)
    }
  })
})
