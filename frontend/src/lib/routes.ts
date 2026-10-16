// Where people start and where they land. Small and dependency-free: the entry page, the
// candidate screens and the staff chunk all use it.

import type { StaffRole } from './staffSession'

/** Code entry: the address an invitation link opens (with ?t=CODE). */
export const CANDIDATE_PATH = '/candidate'

export const LOGIN_PATH = {
  reviewer: '/login/reviewer',
  admin: '/login/admin',
} as const

/** The page a signed-in person starts on. */
export function homeFor(role: StaffRole): '/admin' | '/review' {
  return role === 'admin' ? '/admin' : '/review'
}

/** The sign-in page that belongs to a staff page: admin pages ask for the admin sign-in. */
export function loginPathFor(pathname: string): string {
  const inAdmin = pathname === '/admin' || pathname.startsWith('/admin/')
  return inAdmin ? LOGIN_PATH.admin : LOGIN_PATH.reviewer
}

/** Only ever return to a staff page, never an arbitrary address. */
export function safeNext(next: string | null): string | null {
  return next && /^\/(review|admin)(\/|\?|$)/.test(next) ? next : null
}
