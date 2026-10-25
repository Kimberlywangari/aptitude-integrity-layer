import { api } from './api'
import type { ResumeResponse } from './api'
import { saveSession } from './session'
import { signInBody } from './signIn'
import type { SignIn } from './signIn'

/**
 * Swaps the sign-in (the same as the start page's) for the upload-only key of a finished test (good
 * for 48 hours after it) and keeps it as the session, so the upload screen can send what is left.
 * Throws ApiError: `nothing_to_resume` when there is no finished test, `resume_window_closed` when
 * the 48 hours have passed.
 */
export async function resumeUpload(signIn: SignIn): Promise<void> {
  const body = await api<ResumeResponse>('/api/session/resume', {
    method: 'POST',
    body: signInBody(signIn),
  })
  saveSession(body.session_id, body.access_token)
}
