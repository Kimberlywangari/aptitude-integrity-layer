import { QueryCache, QueryClient } from '@tanstack/vue-query'
import { staffRecovery } from '../lib/api'
import { getStaff } from '../lib/staffSession'

// One client for everything staff-facing. It lives in the lazy staff chunk, so neither it nor
// TanStack Query reaches a candidate's browser.

let client: QueryClient | null = null
let onSessionExpired: (() => void) | null = null

/**
 * What to do when a request finds the session has expired. The staff layout registers it (it knows
 * which router and which page the person is on); it clears the session and goes to the sign-in.
 */
export function setSessionExpiredHandler(handler: (() => void) | null): void {
  onSessionExpired = handler
}

export function getQueryClient(): QueryClient {
  client ??= new QueryClient({
    queryCache: new QueryCache({
      onError: (error) => {
        if (staffRecovery(error) === 'sign-in' && getStaff()) onSessionExpired?.()
      },
    }),
    defaultOptions: { queries: { retry: false, refetchOnWindowFocus: false } },
  })
  return client
}

/** Forget everything the last person saw (sign-out). */
export function clearQueryClient(): void {
  client?.clear()
}
