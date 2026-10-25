/** Seconds from the recording start as m:ss (or h:mm:ss from an hour on). */
export function formatElapsed(totalSeconds: number): string {
  const whole = Math.max(0, Math.round(totalSeconds))
  const h = Math.floor(whole / 3600)
  const m = Math.floor((whole % 3600) / 60)
  const s = whole % 60
  const ss = String(s).padStart(2, '0')
  return h > 0 ? `${h}:${String(m).padStart(2, '0')}:${ss}` : `${m}:${ss}`
}

export function formatDateTime(iso: string | null): string {
  if (!iso) return '-'
  const date = new Date(iso)
  if (Number.isNaN(date.getTime())) return iso
  return date.toLocaleString('en-GB', { dateStyle: 'medium', timeStyle: 'short' })
}

/** "Saturday 24 October at 15:07", in the time zone of whoever is reading: for a candidate told
 *  when a test opens. Falls back to the raw text for something that is not a date. */
export function formatOpensAt(iso: string): string {
  const date = new Date(iso)
  if (Number.isNaN(date.getTime())) return iso
  const day = date.toLocaleDateString('en-GB', { weekday: 'long', day: 'numeric', month: 'long' })
  const time = date.toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit' })
  return `${day} at ${time}`
}

/** SOME_FLAG_KIND -> Some flag kind, for kinds the page has no wording for yet. */
export function humaniseKind(kind: string): string {
  const text = kind.toLowerCase().replace(/_/g, ' ')
  return text.charAt(0).toUpperCase() + text.slice(1)
}

/** 1st, 2nd, 3rd, 4th, 11th, 21st... */
export function ordinal(n: number): string {
  const rest = n % 100
  if (rest >= 11 && rest <= 13) return `${n}th`
  const suffix = { 1: 'st', 2: 'nd', 3: 'rd' }[n % 10] ?? 'th'
  return `${n}${suffix}`
}
