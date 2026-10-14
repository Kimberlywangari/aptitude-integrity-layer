import { getAccessToken } from './session'
import { getStaff } from './staffSession'

// Endpoints the backend does not have yet are served from fixtures when VITE_MOCK_API=1 (set in
// .env.development). Remove a prefix from this list on the day its real endpoint lands and that
// screen talks to the server. The mock module is imported lazily, and the flag is a build-time
// constant, so a production build carries none of it.
const MOCK_ENABLED = import.meta.env.VITE_MOCK_API === '1'
const MOCKED_PREFIXES = ['/api/precheck', '/api/complaints', '/api/chunks', '/api/review', '/api/admin']

/** Reviewer and admin calls carry the staff token; everything else carries the candidate's. */
function isStaffPath(path: string): boolean {
  return path.startsWith('/api/review') || path.startsWith('/api/admin')
}

export class ApiError extends Error {
  status: number
  code: string
  body: Record<string, unknown>

  constructor(status: number, code: string, body: Record<string, unknown>) {
    super(code)
    this.status = status
    this.code = code
    this.body = body
  }
}

let onSebRequired: (() => void) | null = null

/** The app registers where to go when the server says this request did not come from SEB. */
export function setSebRequiredHandler(handler: (() => void) | null): void {
  onSebRequired = handler
}

interface RequestOptions {
  method?: 'GET' | 'POST'
  body?: unknown
}

export async function api<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const token = isStaffPath(path) ? (getStaff()?.token ?? null) : getAccessToken()
  if (MOCK_ENABLED && MOCKED_PREFIXES.some((prefix) => path.startsWith(prefix))) {
    const { mockApi } = await import('./mock')
    return mockApi<T>(path, options.method ?? 'GET', options.body, token)
  }

  const headers: Record<string, string> = {}
  let body: string | undefined
  if (options.body !== undefined) {
    headers['Content-Type'] = 'application/json'
    body = JSON.stringify(options.body)
  }
  if (token) headers.Authorization = `Bearer ${token}`

  const response = await fetch(path, { method: options.method ?? 'GET', headers, body })
  if (response.status === 204) return undefined as T

  const data = (await response.json().catch(() => ({}))) as Record<string, unknown>
  if (!response.ok) {
    const code = typeof data.code === 'string' ? data.code : 'unknown'
    if (response.status === 403 && code === 'seb_required') onSebRequired?.()
    throw new ApiError(response.status, code, data)
  }
  return data as T
}

// ---- response shapes (backend/app/schemas/session.py)

export type SessionStatus = 'created' | 'in_progress' | 'finished'

export interface StartResponse {
  session_id: string
  access_token: string
  status: SessionStatus
}

export interface BeginResponse {
  status: SessionStatus
  remaining_s: number
}

export interface QuestionResponse {
  position: number
  total: number
  section: string
  text: string
  options: { id: number; text: string }[]
  remaining_s: number
}

export interface ResolveResponse {
  done: boolean
  remaining_s: number
}

export interface FinishResponse {
  status: SessionStatus
  total: number
  answered: number
  skipped: number
  unanswered: number
}

// ---- pre-check, upload status and complaints (D6 and D8)

export interface PrecheckRequest {
  camera_ok: boolean
  mic_ok: boolean
  device_labels: { camera: string; mic: string }
  mic_peak: number
  video_size: { width: number; height: number }
}

export interface PrecheckResponse {
  passed: boolean
}

/** Counts only: a 10 s chunk cadence makes the full list of sequence numbers long for no gain. */
export interface ManifestResponse {
  expected: number | null // null until the test has finished and the total is known
  received: number
  missing: number
  bytes: number
  complete: boolean
}

export type ComplaintCategory = 'camera' | 'upload' | 'other'

export interface ComplaintRequest {
  category: ComplaintCategory
  text: string
}

/**
 * Where a candidate belongs after one of the flow's "you are in the wrong place" errors, or
 * null when the error is something else. Keeps every screen's recovery rule in one place.
 */
export function pathForError(error: unknown): string | null {
  if (!(error instanceof ApiError)) return null
  switch (error.code) {
    case 'precheck_required':
      return '/precheck'
    case 'not_started':
      return '/integrity'
    case 'finished':
    case 'time_up':
      return '/done'
    case 'unauthorized':
      return '/'
    default:
      return null
  }
}

/** Where a signed-out or under-privileged staff member goes, or null for any other error. */
export function staffPathForError(error: unknown): string | null {
  if (!(error instanceof ApiError)) return null
  if (error.code === 'unauthorized' || error.code === 'invalid_credentials') return '/review/login'
  if (error.code === 'forbidden') return '/review'
  return null
}
