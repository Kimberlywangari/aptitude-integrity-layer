// Which browser this is, and whether it can record at all. The test is tested on desktop Chrome and
// Edge; any other browser gets a warning, not a block (a user-agent string is a hint, and a
// candidate with a working camera on another browser should not be turned away by a guess).

export type BrowserName = 'Chrome' | 'Edge' | 'Firefox' | 'Safari' | 'Other'

export interface BrowserInfo {
  name: BrowserName
  version: string
  /** False on phones, tablets and Chromebooks, which cannot sit the test. */
  desktop: boolean
}

export function detectBrowser(ua: string = navigator.userAgent): BrowserInfo {
  const desktop = !/Android|iPhone|iPad|iPod|Mobile|CrOS|Tablet/i.test(ua)
  const pick = (re: RegExp, name: BrowserName): BrowserInfo | null => {
    const match = ua.match(re)
    return match ? { name, version: match[1], desktop } : null
  }
  // Order matters: Edge and Opera also say "Chrome", and Chrome also says "Safari".
  return (
    pick(/Edg(?:e|A|iOS)?\/(\d+[\d.]*)/, 'Edge') ??
    (/OPR\//.test(ua) ? { name: 'Other', version: '', desktop } : null) ??
    pick(/Chrome\/(\d+[\d.]*)/, 'Chrome') ??
    pick(/Firefox\/(\d+[\d.]*)/, 'Firefox') ??
    pick(/Version\/(\d+[\d.]*).*Safari/, 'Safari') ?? { name: 'Other', version: '', desktop }
  )
}

export function isSupportedBrowser(info: BrowserInfo): boolean {
  return info.desktop && (info.name === 'Chrome' || info.name === 'Edge')
}

/**
 * Why the camera and microphone cannot even be asked for, or null when they can:
 * 'insecure' is an address that is not HTTPS (and not localhost); 'no_media' is a browser without
 * the camera API.
 */
export function captureProblem(): 'insecure' | 'no_media' | null {
  if (typeof window !== 'undefined' && window.isSecureContext === false) return 'insecure'
  if (typeof navigator === 'undefined' || !navigator.mediaDevices?.getUserMedia) return 'no_media'
  return null
}
