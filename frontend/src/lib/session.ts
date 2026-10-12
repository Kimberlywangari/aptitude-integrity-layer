// The candidate's session lives in sessionStorage: it survives a reload of the tab but not a
// new window, and it is never shared with other origins. Storage can throw (private mode,
// blocked site data), so every access is guarded and the app still renders without it.

const SESSION_ID = 'integrity.session_id'
const ACCESS_TOKEN = 'integrity.access_token'

function read(key: string): string | null {
  try {
    return sessionStorage.getItem(key)
  } catch {
    return null
  }
}

function write(key: string, value: string | null): void {
  try {
    if (value === null) sessionStorage.removeItem(key)
    else sessionStorage.setItem(key, value)
  } catch {
    // storage unavailable: the candidate will be asked for the invitation again on reload
  }
}

export function getSessionId(): string | null {
  return read(SESSION_ID)
}

export function getAccessToken(): string | null {
  return read(ACCESS_TOKEN)
}

export function saveSession(sessionId: string, accessToken: string): void {
  write(SESSION_ID, sessionId)
  write(ACCESS_TOKEN, accessToken)
}

export function clearSession(): void {
  write(SESSION_ID, null)
  write(ACCESS_TOKEN, null)
}
