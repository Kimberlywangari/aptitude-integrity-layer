import { mount } from '@vue/test-utils'
import { nextTick } from 'vue'
import { afterEach, describe, expect, it } from 'vitest'
import type { VideoSegment } from '../src/lib/reviewTypes'
import VideoPlayer from '../src/reviewer/VideoPlayer.vue'
import type { JumpTarget } from '../src/reviewer/VideoPlayer.vue'

afterEach(() => {
  document.body.innerHTML = ''
})

const oneSegment: VideoSegment[] = [{ segment: 0, url: null, start_s: 0, duration_s: 1900 }]
const twoSegments: VideoSegment[] = [
  { segment: 0, url: null, start_s: 0, duration_s: 900 },
  { segment: 1, url: null, start_s: 960, duration_s: 940 },
]

const render = (segments: VideoSegment[], target: JumpTarget | null, deletedAt: string | null = null) =>
  mount(VideoPlayer, { props: { segments, target, deletedAt } })

const part = (w: ReturnType<typeof render>, n: number) =>
  w.findAll('button').find((b) => b.text() === `Part ${n}`)!

describe('VideoPlayer', () => {
  it('says the video was deleted and shows no player', () => {
    const w = render(oneSegment, null, '2026-10-02T10:30:00Z')
    expect(w.text()).toContain('The video was deleted on')
    expect(w.find('video').exists()).toBe(false)
  })

  it('says so when nothing was recorded', () => {
    const w = render([], null)
    expect(w.text()).toContain('No video was recorded for this candidate.')
  })

  it('states where a jump lands, 5 s before the moment', () => {
    const target: JumpTarget = { kind: 'seek', segment: 0, seekS: 305, label: 'F1 Copy', nonce: 1 }
    const w = render(oneSegment, target)
    expect(w.get('[role=status]').text().replace(/\s+/g, ' ')).toBe(
      'F1 Copy: part 1 at 5:05, starting 5 s before the moment.',
    )
  })

  it('says when there is no video at the moment', () => {
    const target: JumpTarget = { kind: 'none', label: 'F3 Run', nonce: 1 }
    const w = render(twoSegments, target)
    expect(w.get('[role=status]').text()).toContain('no video was recorded at this moment')
  })

  it('switches to the part a jump points at', async () => {
    const target: JumpTarget = { kind: 'seek', segment: 1, seekS: 735, label: 'F2', nonce: 1 }
    const w = render(twoSegments, target)
    await nextTick()
    expect(part(w, 2).classes()).not.toContain('secondary')
    expect(part(w, 1).classes()).toContain('secondary')
  })

  it('follows a later jump to another part', async () => {
    const w = render(twoSegments, null)
    expect(part(w, 1).classes()).not.toContain('secondary')
    await w.setProps({ target: { kind: 'seek', segment: 1, seekS: 10, label: 'F2', nonce: 2 } })
    await nextTick()
    expect(part(w, 2).classes()).not.toContain('secondary')
  })

  it('lets the reviewer pick a part by hand', async () => {
    const w = render(twoSegments, null)
    await part(w, 2).trigger('click')
    expect(part(w, 2).classes()).not.toContain('secondary')
  })

  it('seeks a loaded player straight away and a fresh part once it has its metadata', async () => {
    const segments: VideoSegment[] = [
      { segment: 0, url: 'blob:one', start_s: 0, duration_s: 900 },
      { segment: 1, url: 'blob:two', start_s: 960, duration_s: 940 },
    ]
    const w = mount(VideoPlayer, {
      props: { segments, target: null, deletedAt: null },
      attachTo: document.body,
    })
    const first = w.get('video').element as HTMLVideoElement
    Object.defineProperty(first, 'readyState', { value: 4, configurable: true })

    await w.setProps({ target: { kind: 'seek', segment: 0, seekS: 42, label: 'F1', nonce: 1 } })
    await nextTick()
    expect(first.currentTime).toBe(42) // already loaded: no waiting

    await w.setProps({ target: { kind: 'seek', segment: 1, seekS: 77, label: 'F2', nonce: 2 } })
    await nextTick()
    const second = w.get('video').element as HTMLVideoElement
    expect(second).not.toBe(first) // a new part is a new element
    expect(second.currentTime).toBe(0) // not loaded yet
    await w.get('video').trigger('loadedmetadata')
    expect(second.currentTime).toBe(77)
  })

  describe('the timeline of flags', () => {
    const marks = [
      { id: 'F1', label: 'F1 Copy at 8:40', segment: 0, seekS: 515 },
      { id: 'F2', label: 'F2 Focus lost at 28:20', segment: 1, seekS: 735 },
    ]
    const withMarks = (segments: VideoSegment[], list = marks) =>
      mount(VideoPlayer, { props: { segments, target: null, deletedAt: null, marks: list } })
    const left = (w: ReturnType<typeof withMarks>, index: number) =>
      (w.findAll('.timeline .mk')[index].element as HTMLElement).style.left

    it('puts each flag where it falls in the whole recording, parts laid end to end', () => {
      const w = withMarks(twoSegments)
      expect(w.findAll('.timeline .mk')).toHaveLength(2)
      // the player lands 5 s before the moment, so the marker sits 5 s after the landing point
      expect(parseFloat(left(w, 0))).toBeCloseTo((515 + 5) / 1900 * 100, 3)
      expect(parseFloat(left(w, 1))).toBeCloseTo((960 + 735 + 5) / 1900 * 100, 3)
    })

    it('names each marker for a screen reader and for a mouse', () => {
      const w = withMarks(twoSegments)
      const first = w.findAll('.timeline .mk')[0]
      expect(first.attributes('aria-label')).toBe('Jump to F1 Copy at 8:40')
      expect(first.attributes('title')).toBe('F1 Copy at 8:40')
    })

    it('tells the page which flag was clicked', async () => {
      const w = withMarks(twoSegments)
      await w.findAll('.timeline .mk')[1].trigger('click')
      expect(w.emitted('mark')).toEqual([['F2']])
    })

    it('draws no timeline when no flag has video', () => {
      expect(withMarks(twoSegments, []).find('.timeline').exists()).toBe(false)
    })

    it('leaves out a flag whose part is not in the recording', () => {
      const w = withMarks(oneSegment, marks)
      expect(w.findAll('.timeline .mk')).toHaveLength(1) // part 2 does not exist here
    })

    it('moves the playhead as the video plays', async () => {
      const segments: VideoSegment[] = [{ segment: 0, url: 'blob:one', start_s: 0, duration_s: 1900 }]
      const w = mount(VideoPlayer, {
        props: { segments, target: null, deletedAt: null, marks },
        attachTo: document.body,
      })
      const element = w.get('video').element as HTMLVideoElement
      element.currentTime = 95
      await w.get('video').trigger('timeupdate')
      expect(parseFloat((w.get('.playhead').element as HTMLElement).style.left)).toBeCloseTo(5, 3)
    })
  })
})
