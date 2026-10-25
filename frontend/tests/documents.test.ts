import { flushPromises } from '@vue/test-utils'
import type { VueWrapper } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { documentProblem } from '../src/lib/readDocument'
import { ApiError } from '../src/lib/api'
import { resetMock, setMockLatency } from './mock'
import { clearStaff, saveStaff } from '../src/lib/staffSession'
import { clearQueryClient } from '../src/staff/queryClient'
import { renderApp, until } from './helpers/render'

vi.mock('../src/lib/api', async (importOriginal) =>
  (await import('./helpers/mockedApi')).withMockedApi(await importOriginal()),
)

async function renderAt(path: string) {
  const { wrapper } = await renderApp(path)
  await flushPromises()
  return wrapper
}

const norm = (text: string) => text.replace(/\s+/g, ' ').trim()
const untilText = (w: VueWrapper, re: RegExp | string) =>
  until(() => (typeof re === 'string' ? norm(w.text()).includes(re) : re.test(norm(w.text()))))
/** Chooses a file in a file input, the way the browser's file picker would. */
async function choose(input: ReturnType<VueWrapper['get']>, name: string, content: string) {
  const file = new File([content], name)
  Object.defineProperty(input.element, 'files', { value: [file], configurable: true })
  await input.trigger('change')
  await flushPromises()
}

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

describe('choosing a file for the invitation list', () => {
  it('takes any kind of file, with no list of allowed types', async () => {
    const w = await renderAt('/admin/invites')
    await until(() => w.find('input[aria-label="Upload a list"]').exists())
    expect(w.get('input[aria-label="Upload a list"]').attributes('accept')).toBeUndefined()
  })

  it('puts the words the server read out of a spreadsheet into the box', async () => {
    const w = await renderAt('/admin/invites')
    await until(() => w.find('#people').exists())
    await choose(
      w.get('input[aria-label="Upload a list"]'),
      'people.xlsx', // the name means nothing; the server looks at the bytes
      'SHEET:Ada Lovelace,ada@example.org\nGrace Hopper,grace@navy.test\n',
    )
    await until(() => (w.get('#people').element as HTMLTextAreaElement).value !== '')
    expect((w.get('#people').element as HTMLTextAreaElement).value).toBe(
      'Ada Lovelace,ada@example.org\nGrace Hopper,grace@navy.test\n',
    )
  })

  it.each([
    ['LEGACY old word file', 'old Word, Excel or PowerPoint file'],
    ['SCANNED pages', 'pictures of pages'],
    ['LOCKED secret', 'password protected'],
  ])('says plainly why %s cannot be used, and leaves the box as it was', async (content, words) => {
    const w = await renderAt('/admin/invites')
    await until(() => w.find('#people').exists())
    await w.get('#people').setValue('Ada Lovelace, ada@example.org')
    await choose(w.get('input[aria-label="Upload a list"]'), 'list.doc', content)
    await untilText(w, words)
    expect((w.get('#people').element as HTMLTextAreaElement).value).toBe(
      'Ada Lovelace, ada@example.org',
    )
  })

  it('says so for an empty file', async () => {
    const w = await renderAt('/admin/invites')
    await until(() => w.find('#people').exists())
    await choose(w.get('input[aria-label="Upload a list"]'), 'list.txt', '   ')
    await untilText(w, 'That file is empty.')
  })

  it('clears the old complaint once a good file is chosen', async () => {
    const w = await renderAt('/admin/invites')
    await until(() => w.find('#people').exists())
    const input = w.get('input[aria-label="Upload a list"]')
    await choose(input, 'list.doc', 'LEGACY')
    await untilText(w, 'old Word, Excel or PowerPoint file')
    await choose(input, 'list.xlsx', 'SHEET:Ada,ada@example.org\n')
    await until(() => !norm(w.text()).includes('old Word, Excel or PowerPoint file'))
    expect((w.get('#people').element as HTMLTextAreaElement).value).toBe('Ada,ada@example.org\n')
  })
})

describe('choosing files for the question import', () => {
  const HEADER = 'question_id,section,correct_option,difficulty_tag,n_candidates,pct_correct,median_s,p25_s,p75_s'

  async function ready() {
    const { mockApi } = await import('./mock')
    await mockApi('/api/admin/sittings/1/close', 'POST', { force: true }, 'mock-admin:admin@example.com')
    const w = await renderAt('/admin/questions')
    await until(() => w.find('#summary').exists())
    return w
  }

  it('takes any kind of file in both places', async () => {
    const w = await ready()
    expect(w.get('#summary').attributes('accept')).toBeUndefined()
    expect(w.get('#bank').attributes('accept')).toBeUndefined()
  })

  it('imports a spreadsheet of questions as it would a CSV', async () => {
    const w = await ready()
    await choose(w.get('#summary'), 'questions.xlsx', `SHEET:${HEADER}\nQ001,verbal,b,hard,812,38.5,71,50,96\n`)
    await w.get('form').trigger('submit')
    await untilText(w, 'questions.xlsx: 1 of 1 rows imported')
  })

  it('says there is no table instead of guessing, when the file is only words', async () => {
    const w = await ready()
    await choose(w.get('#summary'), 'letter.pdf', 'A letter about the questions with no table in it')
    await w.get('form').trigger('submit')
    await untilText(w, 'No table was found in that file')
  })

  it('says why an old binary spreadsheet cannot be read', async () => {
    const w = await ready()
    await choose(w.get('#summary'), 'questions.xls', 'LEGACY')
    await w.get('form').trigger('submit')
    await untilText(w, 'save it as .docx, .xlsx or .pptx')
  })
})

describe('the wording for a file that could not be read', () => {
  it('knows every code the server can answer with', () => {
    const codes = [
      'empty_file',
      'file_too_large',
      'legacy_office_format',
      'scanned_pdf',
      'password_protected',
      'no_table_found',
      'no_text_found',
      'too_much_text',
      'unsupported_type',
      'unreadable_file',
    ]
    for (const code of codes) {
      expect(documentProblem(new ApiError(422, code, { code }))).toMatch(/\w+/)
    }
  })

  it('says nothing for a problem that was not the file’s', () => {
    expect(documentProblem(new ApiError(500, 'something_else', {}))).toBeNull()
    expect(documentProblem(new Error('offline'))).toBeNull()
  })
})
