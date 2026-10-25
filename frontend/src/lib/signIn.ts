import { normaliseInviteCode } from './inviteCode'

/** What the start page and the upload page collect. See backend/app/services/login.py for what the
 *  server makes of each combination: code and email the first time (then a password is chosen),
 *  email and password after that, and the code alone for an invitation made without an email. */
export interface SignIn {
  token: string
  email: string
  password: string
  /** Set when the candidate is choosing their password at their first sign-in. */
  newPassword?: string
}

export const MIN_PASSWORD_CHARS = 8

/** The request body: whatever is empty is left out, the code is read forgivingly (lib/inviteCode). */
export function signInBody(s: SignIn) {
  const token = s.token.trim()
  return {
    token: token ? normaliseInviteCode(token) : undefined,
    email: s.email.trim() || undefined,
    password: s.password || undefined,
    new_password: s.newPassword || undefined,
  }
}

/** Whether there is enough to send: a code, or an email with a password. */
export const canSignIn = (s: SignIn) => s.token.trim() !== '' || (s.email.trim() !== '' && s.password !== '')
