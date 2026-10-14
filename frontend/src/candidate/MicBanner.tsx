import { useSyncExternalStore } from 'react'
import { getMicSilent, subscribeMicSilent } from '../lib/micStatus'
import { MIC_BANNER } from './copy'

/**
 * Warning shown above the question while the microphone looks muted or silent. It never blocks:
 * no button is disabled, the countdown keeps running and no request changes.
 */
export default function MicBanner() {
  const silent = useSyncExternalStore(subscribeMicSilent, getMicSilent)
  // The live region stays mounted so a screen reader announces the text when it appears.
  return <div role="status">{silent && <p className="banner">{MIC_BANNER}</p>}</div>
}
