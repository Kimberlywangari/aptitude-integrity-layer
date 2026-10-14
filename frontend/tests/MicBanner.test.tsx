import { act, cleanup, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it } from 'vitest'
import MicBanner from '../src/candidate/MicBanner'
import { MIC_BANNER } from '../src/candidate/copy'
import { setMicSilent } from '../src/lib/micStatus'

afterEach(() => {
  act(() => setMicSilent(false))
  cleanup()
})

describe('MicBanner', () => {
  it('shows nothing while the microphone looks fine', () => {
    render(<MicBanner />)
    expect(screen.queryByText(MIC_BANNER)).toBeNull()
  })

  it('appears when the microphone looks muted or silent and clears when it recovers', () => {
    render(<MicBanner />)
    act(() => setMicSilent(true))
    expect(screen.getByText(MIC_BANNER)).toBeTruthy()
    act(() => setMicSilent(false))
    expect(screen.queryByText(MIC_BANNER)).toBeNull()
  })

  it('announces itself politely and never takes focus or blocks anything', () => {
    render(<MicBanner />)
    act(() => setMicSilent(true))
    const region = screen.getByRole('status')
    expect(region.getAttribute('aria-live')).toBeNull() // role=status is already polite
    expect(region.querySelector('button, input, a')).toBeNull()
  })
})
