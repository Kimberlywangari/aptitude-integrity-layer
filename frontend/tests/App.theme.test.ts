import { flushPromises } from '@vue/test-utils'
import { afterEach, describe, expect, it } from 'vitest'
import { renderApp } from './helpers/render'

// The toggle is mounted once in the App shell, outside the routes, so every screen has it. This
// guards that arrangement: moving it inside a route would drop it from the other screens.
describe('light and dark toggle', () => {
  afterEach(() => {
    document.body.innerHTML = ''
  })

  it.each([
    '/',
    '/candidate',
    '/precheck',
    '/integrity',
    '/test',
    '/done',
    '/uploading',
    '/complaint',
    '/login/reviewer',
    '/login/admin',
    '/no/such/page',
  ])('is on %s', async (path) => {
    const { wrapper } = await renderApp(path)
    await flushPromises()
    const toggle = wrapper.findAll('button').find((b) => /^(dark|light) mode$/i.test(b.text()))
    expect(toggle).toBeTruthy()
  })
})
