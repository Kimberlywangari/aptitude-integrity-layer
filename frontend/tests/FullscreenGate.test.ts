import { mount } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import FullscreenGate from '../src/candidate/FullscreenGate.vue'
import { enterFullscreen } from '../src/lib/fullscreen'
import { resetFullscreen } from './helpers/fakeFullscreen'
import { settle } from './helpers/render'

vi.mock('../src/lib/fullscreen', async () => (await import('./helpers/fakeFullscreen')).fullscreenModule)

describe('FullscreenGate', () => {
  beforeEach(() => {
    resetFullscreen()
    vi.mocked(enterFullscreen).mockClear()
  })

  afterEach(() => {
    document.body.innerHTML = ''
  })

  it('is a labelled dialog that names the time left and puts focus on its button', () => {
    const w = mount(FullscreenGate, { props: { timeLeft: '12:34' }, attachTo: document.body })
    const dialog = w.get('[role=dialog]')
    expect(dialog.attributes('aria-modal')).toBe('true')
    expect(dialog.attributes('aria-labelledby')).toBe('fullscreen-title')
    expect(w.get('#fullscreen-title').text()).toBe('Return to full screen')
    expect(w.text()).toContain('12:34')
    expect(document.activeElement).toBe(w.get('button').element)
  })

  it('asks the browser for full screen when the button is pressed', async () => {
    const w = mount(FullscreenGate, { props: { timeLeft: '12:34' } })
    await w.get('button').trigger('click')
    await settle()
    expect(enterFullscreen).toHaveBeenCalledOnce()
    expect(w.find('[role=alert]').exists()).toBe(false)
  })

  it('says so when the browser refuses', async () => {
    vi.mocked(enterFullscreen).mockResolvedValueOnce(false)
    const w = mount(FullscreenGate, { props: { timeLeft: '12:34' } })
    await w.get('button').trigger('click')
    await settle()
    expect(w.get('[role=alert]').text()).toContain('did not switch to full screen')
  })
})
