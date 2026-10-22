/** "about 1 minute", "about 3 minutes": a lock's length rounded up, for people to read. */
export function waitPhrase(seconds: number): string {
  const minutes = Math.max(1, Math.ceil(seconds / 60))
  return `about ${minutes} minute${minutes === 1 ? '' : 's'}`
}
