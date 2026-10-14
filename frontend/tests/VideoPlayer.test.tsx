import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it } from 'vitest'
import type { VideoSegment } from '../src/lib/reviewTypes'
import VideoPlayer from '../src/reviewer/VideoPlayer'
import type { JumpTarget } from '../src/reviewer/VideoPlayer'

afterEach(cleanup)

const oneSegment: VideoSegment[] = [{ segment: 0, url: null, start_s: 0, duration_s: 1900 }]
const twoSegments: VideoSegment[] = [
  { segment: 0, url: null, start_s: 0, duration_s: 900 },
  { segment: 1, url: null, start_s: 960, duration_s: 940 },
]

describe('VideoPlayer', () => {
  it('says the video was deleted and shows no player', () => {
    render(<VideoPlayer segments={oneSegment} target={null} deletedAt="2026-10-02T10:30:00Z" />)
    expect(screen.getByText(/The video was deleted on/)).toBeTruthy()
    expect(document.querySelector('video')).toBeNull()
  })

  it('says so when nothing was recorded', () => {
    render(<VideoPlayer segments={[]} target={null} deletedAt={null} />)
    expect(screen.getByText('No video was recorded for this candidate.')).toBeTruthy()
  })

  it('states where a jump lands, 5 s before the moment', () => {
    const target: JumpTarget = { kind: 'seek', segment: 0, seekS: 305, label: 'F1 Copy', nonce: 1 }
    render(<VideoPlayer segments={oneSegment} target={target} deletedAt={null} />)
    expect(screen.getByRole('status').textContent).toBe(
      'F1 Copy: part 1 at 5:05, starting 5 s before the moment.',
    )
  })

  it('says when there is no video at the moment', () => {
    const target: JumpTarget = { kind: 'none', label: 'F3 Run', nonce: 1 }
    render(<VideoPlayer segments={twoSegments} target={target} deletedAt={null} />)
    expect(screen.getByRole('status').textContent).toContain('no video was recorded at this moment')
  })

  it('switches to the part a jump points at', () => {
    const target: JumpTarget = { kind: 'seek', segment: 1, seekS: 735, label: 'F2', nonce: 1 }
    render(<VideoPlayer segments={twoSegments} target={target} deletedAt={null} />)
    const part2 = screen.getByRole('button', { name: 'Part 2' })
    expect(part2.className).not.toContain('secondary')
    expect(screen.getByRole('button', { name: 'Part 1' }).className).toContain('secondary')
  })

  it('lets the reviewer pick a part by hand', () => {
    render(<VideoPlayer segments={twoSegments} target={null} deletedAt={null} />)
    fireEvent.click(screen.getByRole('button', { name: 'Part 2' }))
    expect(screen.getByRole('button', { name: 'Part 2' }).className).not.toContain('secondary')
  })
})
