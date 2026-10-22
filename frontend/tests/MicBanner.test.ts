import { mount } from '@vue/test-utils'
import { nextTick } from 'vue'
import { afterEach, describe, expect, it } from 'vitest'
import MicBanner from '../src/candidate/MicBanner.vue'
import { MIC_BANNER } from '../src/candidate/copy'
import { setMicSilent } from '../src/lib/micStatus'

afterEach(() => {
  setMicSilent(false)
  document.body.innerHTML = ''
})

describe('MicBanner', () => {
  it('shows nothing while the microphone looks fine', () => {
    const wrapper = mount(MicBanner)
    expect(wrapper.text()).not.toContain(MIC_BANNER)
  })

  it('appears when the microphone looks muted or silent and clears when it recovers', async () => {
    const wrapper = mount(MicBanner)
    setMicSilent(true)
    await nextTick()
    expect(wrapper.text()).toContain(MIC_BANNER)
    setMicSilent(false)
    await nextTick()
    expect(wrapper.text()).not.toContain(MIC_BANNER)
  })

  it('announces itself politely and never takes focus or blocks anything', async () => {
    const wrapper = mount(MicBanner)
    setMicSilent(true)
    await nextTick()
    const region = wrapper.get('[role=status]')
    expect(region.attributes('aria-live')).toBeUndefined() // role=status is already polite
    expect(region.find('button, input, a').exists()).toBe(false)
  })
})
