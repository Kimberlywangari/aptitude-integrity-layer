// Invitation codes are 8 characters from Crockford's base32 alphabet (no I, L, O or U), shown as
// XXXX-XXXX. Candidates sometimes type them by hand from an email or a message, so input is forgiving:
// case, spaces, dashes and underscores are ignored and the look-alikes O, I and L are read as
// 0, 1 and 1. The server applies the same rule before it hashes the code
// (backend/app/core/security.py, normalise_invite_code), so keep the two in step. Anything that
// does not look like a short code (the long hex tokens from the first seed) is passed through
// untouched, so existing invitations keep working.

export const INVITE_ALPHABET = '0123456789ABCDEFGHJKMNPQRSTVWXYZ'
export const INVITE_LENGTH = 8

const SHORT_CODE = new RegExp(`^[${INVITE_ALPHABET}]{${INVITE_LENGTH}}$`)
const NOT_PLAIN_ASCII = /[^\t\x20-\x7E]/

export function normaliseInviteCode(input: string): string {
  const trimmed = input.trim()
  // Only plain ASCII is ever folded: toUpperCase would turn a German sharp s into SS.
  if (NOT_PLAIN_ASCII.test(trimmed)) return trimmed
  const cleaned = trimmed
    .replace(/[\s_-]/g, '')
    .toUpperCase()
    .replace(/O/g, '0')
    .replace(/[IL]/g, '1')
  return SHORT_CODE.test(cleaned) ? cleaned : trimmed
}

/** XXXX-XXXX for a short code; anything else is returned as it is. */
export function formatInviteCode(code: string): string {
  const half = INVITE_LENGTH / 2
  return SHORT_CODE.test(code) ? `${code.slice(0, half)}-${code.slice(half)}` : code
}
