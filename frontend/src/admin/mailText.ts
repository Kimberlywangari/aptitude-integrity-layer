import type { MailState } from '../lib/adminTypes'

/** What the Resend link button does, said where it is pointed at: it is also how a forgotten
 *  password is fixed, because they choose a new one at their next sign-in. */
export const RESEND_TITLE =
  'Makes a new code, stops the old one working, clears their password and emails the new link ' +
  '(a candidate who has already finished is not emailed: pass the link on yourself).'

/** What an email's state is called on the admin screens, and the colour of its pill. */
export const MAIL: Record<MailState, { label: string; pill: string }> = {
  queued: { label: 'Waiting to send', pill: 'plain' },
  sent: { label: 'Email sent', pill: 'ok' },
  failed: { label: 'Email failed', pill: 'high' },
}
