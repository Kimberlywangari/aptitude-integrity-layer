// Feature switches. Like VITE_MOCK_API these are read when the dev server starts, so change the
// line and restart `npm run dev`. Every switch defaults to ON: with no setting, the app behaves as
// it will in the pilot.

/**
 * The microphone step of the pre-check (level meter and the "say your name" check), and the
 * mid-test warning banner. Set VITE_MIC_CHECK=off to leave it out while the rest of the exam flow
 * is being tested. Personal setting: put it in frontend/.env.development.local, which git ignores.
 *
 * This only moves the browser side. When the server gets its own pre-check gate (D6) it needs its
 * own setting: a switch in the candidate's browser cannot be what decides whether a candidate passes.
 */
export function micCheckEnabled(): boolean {
  return import.meta.env.VITE_MIC_CHECK !== 'off'
}

/**
 * The full-screen step of the pre-check and the "return to full screen" cover during the test.
 * Set VITE_FULLSCREEN=off only for automated browser runs, where full screen is not available.
 * Like every switch here it defaults to ON, which is how the pilot runs.
 */
export function fullscreenRequired(): boolean {
  return import.meta.env.VITE_FULLSCREEN !== 'off'
}
