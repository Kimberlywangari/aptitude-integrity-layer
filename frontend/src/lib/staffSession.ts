// Reviewer and admin login. Same rules as the candidate session: sessionStorage only, every
// access guarded, and the app still renders when storage is blocked (the staff member just has
// to sign in again).

const KEY = 'integrity.staff'

export type StaffRole = 'reviewer' | 'admin'

export interface StaffSession {
  token: string
  email: string
  role: StaffRole
}

function isSession(value: unknown): value is StaffSession {
  if (typeof value !== 'object' || value === null) return false
  const v = value as Record<string, unknown>
  return (
    typeof v.token === 'string' &&
    typeof v.email === 'string' &&
    (v.role === 'reviewer' || v.role === 'admin')
  )
}

export function getStaff(): StaffSession | null {
  try {
    const raw = sessionStorage.getItem(KEY)
    if (!raw) return null
    const parsed: unknown = JSON.parse(raw)
    return isSession(parsed) ? parsed : null
  } catch {
    return null
  }
}

export function saveStaff(session: StaffSession): void {
  try {
    sessionStorage.setItem(KEY, JSON.stringify(session))
  } catch {
    // storage unavailable: the next reload asks for the password again
  }
}

export function clearStaff(): void {
  try {
    sessionStorage.removeItem(KEY)
  } catch {
    // nothing to clear
  }
}
