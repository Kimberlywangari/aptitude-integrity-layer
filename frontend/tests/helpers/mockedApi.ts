import { vi } from 'vitest'
import type * as ApiModule from '../../src/lib/api'

/**
 * For vi.mock('../src/lib/api', ...): keeps the real ApiError and error helpers but routes api()
 * through the in-memory mock backend, so a screen can be rendered against fixtures.
 */
export function withMockedApi(actual: typeof ApiModule): typeof ApiModule {
  const api = vi.fn(
    async (
      path: string,
      options: { method?: string; body?: unknown; bytes?: Blob } = {},
    ): Promise<unknown> => {
      const { mockApi } = await import('../mock')
      const { getStaff } = await import('../../src/lib/staffSession')
      const { getAccessToken } = await import('../../src/lib/session')
      const staffPath = path.startsWith('/api/review') || path.startsWith('/api/admin')
      const token = staffPath ? (getStaff()?.token ?? null) : getAccessToken()
      return mockApi(path, options.method ?? 'GET', options.body ?? options.bytes, token)
    },
  )
  return { ...actual, api: api as unknown as typeof ApiModule.api }
}
