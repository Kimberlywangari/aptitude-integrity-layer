// The candidate's session lives in sessionStorage: it survives a reload of the tab but not a
// new window, and it is never shared with other origins. Storage can throw (private mode,
// blocked site data), so every access is guarded and the app still renders without it.

const SESSION_ID = 'integrity.session_id'
const ACCESS_TOKEN = 'integrity.access_token'
const STAGE = 'integrity.stage'

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

/** How far past the questions this tab has got: the test is over (`finished`), or the closing
 *  question has been answered and only the upload is left (`reported`). Kept so the router can
 *  refuse a way back to the test after Back is pressed. */
export type Stage = 'finished' | 'reported'

export function getStage(): Stage | null {
  const stage = read(STAGE)
  return stage === 'finished' || stage === 'reported' ? stage : null
}

export function setStage(stage: Stage): void {
  write(STAGE, stage)
}

// A new or resumed session starts its own journey, so an earlier one's stage must not carry over.
export function saveSession(sessionId: string, accessToken: string): void {
  write(SESSION_ID, sessionId)
  write(ACCESS_TOKEN, accessToken)
  write(STAGE, null)
}

export function clearSession(): void {
  write(SESSION_ID, null)
  write(ACCESS_TOKEN, null)
  write(STAGE, null)
}
