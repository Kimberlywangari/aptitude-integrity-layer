import { afterEach, describe, expect, it } from 'vitest'
import { createMemoryHistory } from 'vue-router'
import Entry from '../src/entry/Entry.vue'
import { createAppRouter } from '../src/router'
import { mountPage } from './helpers/render'

afterEach(() => {
  document.body.innerHTML = ''
})

describe('entry page', () => {
  it('offers one door for each kind of person', async () => {
    const { wrapper } = await mountPage('/', { '/': Entry })
    const links = wrapper.findAll('ul a').map((a) => [a.text(), a.attributes('href')])

    expect(links).toEqual([
      [expect.stringMatching(/^Candidate/), '/candidate'],
      [expect.stringMatching(/^Reviewer/), '/login/reviewer'],
      [expect.stringMatching(/^Admin/), '/login/admin'],
    ])
  })

  it('shows the page when there is no invitation code', async () => {
    const { wrapper } = await mountPage('/?other=1', { '/': Entry })
    expect(wrapper.get('h1').text()).toBe('Aptitude test')
  })
})

// The forward from an old invitation link lives in the router, so the candidate never sees the
// chooser flash by.
describe('old invitation links', () => {
  it('forward to code entry, keeping the code', async () => {
    const router = createAppRouter(createMemoryHistory())
    await router.push('/?t=ABCD-EFGH')
    expect(router.currentRoute.value.fullPath).toBe('/candidate?t=ABCD-EFGH')
  })

  it('keep a code with spaces and symbols exactly as it was', async () => {
    const router = createAppRouter(createMemoryHistory())
    await router.push('/?t=a%20b%26c')
    expect(router.currentRoute.value.path).toBe('/candidate')
    expect(router.currentRoute.value.query.t).toBe('a b&c')
  })

  it('do not forward when there is no code', async () => {
    const router = createAppRouter(createMemoryHistory())
    await router.push('/?other=1')
    expect(router.currentRoute.value.path).toBe('/')
  })
})
