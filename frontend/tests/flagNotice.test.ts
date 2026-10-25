import { mount } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import FlagNotice from '../src/candidate/FlagNotice.vue'
import { FLAG_NOTICE } from '../src/candidate/copy'
import { clearNotice, noteRecorded, noticeVisible, QUIET_MS, SHOW_MS } from '../src/lib/flagNotice'

describe('the notice that something was recorded', () => {
  beforeEach(() => {
    vi.useFakeTimers()
    clearNotice()
  })

  afterEach(() => {
    clearNotice()
    vi.useRealTimers()
  })

  it('appears, then goes by itself after a few seconds', () => {
    noteRecorded(0)
    expect(noticeVisible.value).toBe(true)
    vi.advanceTimersByTime(SHOW_MS - 1)
    expect(noticeVisible.value).toBe(true)
    vi.advanceTimersByTime(1)
    expect(noticeVisible.value).toBe(false)
  })

  it('does not come again while it is still quiet, so a burst of events does not flicker', () => {
    noteRecorded(0)
    vi.advanceTimersByTime(SHOW_MS)
    noteRecorded(SHOW_MS + 1_000) // inside the quiet period
    expect(noticeVisible.value).toBe(false)
    noteRecorded(QUIET_MS) // after it
    expect(noticeVisible.value).toBe(true)
  })

  it('reads calmly: nothing about a rule, a number or cheating', () => {
    for (const word of ['flag', 'cheat', 'rule', 'threshold', 'score', 'AI ']) {
      expect(FLAG_NOTICE.toLowerCase()).not.toContain(word.toLowerCase())
    }
    expect(FLAG_NOTICE).toBe(
      'This has been recorded and a reviewer will see it. Nothing has been decided.',
    )
  })

  it('shows as a polite status line that cannot be clicked into', () => {
    noteRecorded(0)
    const w = mount(FlagNotice)
    const line = w.get('[role=status]')
    expect(line.text()).toBe(FLAG_NOTICE)
    expect(line.classes()).toContain('flag-notice')
    expect(w.html()).not.toContain('button')
    w.unmount()
  })

  it('shows nothing when nothing was recorded', () => {
    const w = mount(FlagNotice)
    expect(w.find('[role=status]').exists()).toBe(false)
    w.unmount()
  })
})
