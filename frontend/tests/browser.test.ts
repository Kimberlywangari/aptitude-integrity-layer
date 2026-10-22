import { afterEach, describe, expect, it, vi } from 'vitest'
import { captureProblem, detectBrowser, isSupportedBrowser } from '../src/lib/browser'

const UA = {
  chromeWindows:
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/118.0.5993.88 Safari/537.36',
  edgeWindows:
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/118.0.5993.88 Safari/537.36 Edg/118.0.2088.46',
  chromeMac:
    'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/118.0.0.0 Safari/537.36',
  firefox: 'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:119.0) Gecko/20100101 Firefox/119.0',
  safariMac:
    'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Safari/605.1.15',
  chromeAndroid:
    'Mozilla/5.0 (Linux; Android 13; Pixel 7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/118.0.0.0 Mobile Safari/537.36',
  safariIpad:
    'Mozilla/5.0 (iPad; CPU OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1',
  chromebook:
    'Mozilla/5.0 (X11; CrOS x86_64 14541.0.0) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/118.0.0.0 Safari/537.36',
  opera:
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/118.0.0.0 Safari/537.36 OPR/104.0.0.0',
}

describe('detectBrowser()', () => {
  it('tells Chrome and Edge apart, though Edge also says Chrome', () => {
    expect(detectBrowser(UA.chromeWindows)).toEqual({ name: 'Chrome', version: '118.0.5993.88', desktop: true })
    expect(detectBrowser(UA.edgeWindows)).toMatchObject({ name: 'Edge', version: '118.0.2088.46', desktop: true })
  })

  it('names the other desktop browsers', () => {
    expect(detectBrowser(UA.firefox).name).toBe('Firefox')
    expect(detectBrowser(UA.safariMac).name).toBe('Safari')
    expect(detectBrowser(UA.opera).name).toBe('Other')
  })

  it('knows phones, tablets and Chromebooks are not desktops', () => {
    expect(detectBrowser(UA.chromeAndroid).desktop).toBe(false)
    expect(detectBrowser(UA.safariIpad).desktop).toBe(false)
    expect(detectBrowser(UA.chromebook).desktop).toBe(false)
    expect(detectBrowser(UA.chromeMac).desktop).toBe(true)
  })
})

describe('isSupportedBrowser()', () => {
  it('accepts desktop Chrome and Edge only', () => {
    expect(isSupportedBrowser(detectBrowser(UA.chromeWindows))).toBe(true)
    expect(isSupportedBrowser(detectBrowser(UA.edgeWindows))).toBe(true)
    expect(isSupportedBrowser(detectBrowser(UA.chromeMac))).toBe(true)
    expect(isSupportedBrowser(detectBrowser(UA.firefox))).toBe(false)
    expect(isSupportedBrowser(detectBrowser(UA.safariMac))).toBe(false)
    expect(isSupportedBrowser(detectBrowser(UA.chromeAndroid))).toBe(false)
    expect(isSupportedBrowser(detectBrowser(UA.chromebook))).toBe(false)
  })
})

describe('captureProblem()', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('is null when the page is secure and the browser has a camera API', () => {
    vi.stubGlobal('isSecureContext', true)
    vi.stubGlobal('navigator', { mediaDevices: { getUserMedia: () => undefined } })
    expect(captureProblem()).toBeNull()
  })

  it('says the address is not secure when it is not HTTPS', () => {
    vi.stubGlobal('isSecureContext', false)
    vi.stubGlobal('navigator', { mediaDevices: { getUserMedia: () => undefined } })
    expect(captureProblem()).toBe('insecure')
  })

  it('says the browser has no camera API when it has none', () => {
    vi.stubGlobal('isSecureContext', true)
    vi.stubGlobal('navigator', {})
    expect(captureProblem()).toBe('no_media')
  })
})
