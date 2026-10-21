import { api } from './api'
import type { ResumeResponse } from './api'
import { normaliseInviteCode } from './inviteCode'
import { saveSession } from './session'

/**
 * Swaps an invitation code for the upload-only key of a finished test (good for 48 hours after it)
 * and keeps it as the session, so the upload screen can send what is left. Throws ApiError:
 * `nothing_to_resume` when there is no finished test for the code, `resume_window_closed` when the
 * 48 hours have passed.
 */
export async function resumeUpload(invitation: string): Promise<void> {
  const body = await api<ResumeResponse>('/api/session/resume', {
    method: 'POST',
    body: { token: normaliseInviteCode(invitation) },
  })
  saveSession(body.session_id, body.access_token)
}
