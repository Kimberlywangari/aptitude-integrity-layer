export interface Crumb {
  label: string
  to?: string
}

function decoded(part: string): string {
  try {
    return decodeURIComponent(part)
  } catch {
    return part // a stray % in the address is shown as typed
  }
}

/** Where a staff page sits, from its address. A page that is its own section has one crumb. */
export function crumbsFor(pathname: string): Crumb[] {
  const parts = pathname.split('/').filter(Boolean)

  if (parts[0] === 'review') {
    const review = { label: 'Review', to: '/review' }
    if (parts[1] === 'audit') return [review, { label: 'Audit' }]
    if (parts[1] === 'candidates' && parts[2]) {
      return [review, { label: `Candidate ${decoded(parts[2])}` }]
    }
    return [{ label: 'Review' }]
  }

  if (parts[0] === 'admin') {
    const admin = { label: 'Admin', to: '/admin' }
    if (parts[1] === 'invites') return [admin, { label: 'Invites' }]
    if (parts[1] === 'questions') return [admin, { label: 'Questions' }]
    return [{ label: 'Sittings' }]
  }

  return []
}
