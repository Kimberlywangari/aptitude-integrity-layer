import { mount } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it } from 'vitest'
import ThemeToggle from '../src/components/ThemeToggle.vue'

describe('theme toggle', () => {
  beforeEach(() => {
    document.documentElement.dataset.theme = 'light'
    window.localStorage.clear()
  })

  afterEach(() => {
    document.body.innerHTML = ''
  })

  it('offers the opposite of the current theme', () => {
    const wrapper = mount(ThemeToggle)
    expect(wrapper.get('button').text()).toBe('Dark mode')
  })

  it('switches the page and remembers the choice', async () => {
    const wrapper = mount(ThemeToggle)

    await wrapper.get('button').trigger('click')
    expect(document.documentElement.dataset.theme).toBe('dark')
    expect(window.localStorage.getItem('theme')).toBe('dark')
    expect(wrapper.get('button').text()).toBe('Light mode')

    await wrapper.get('button').trigger('click')
    expect(document.documentElement.dataset.theme).toBe('light')
    expect(window.localStorage.getItem('theme')).toBe('light')
  })
})
