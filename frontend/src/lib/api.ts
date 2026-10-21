import { CANDIDATE_PATH } from './routes'
import { getAccessToken } from './session'
import { getStaff } from './staffSession'

// Every screen talks to the real server. The in-memory fixtures in ./mock are for the screen
// tests only (see tests/helpers/mockedApi.ts); nothing in the app imports them.

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

interface RequestOptions {
  method?: 'GET' | 'POST' | 'PUT'
  body?: unknown
  /** Raw bytes sent as they are, instead of JSON: one chunk of the recording. */
  bytes?: Blob
  headers?: Record<string, string>
  /** Lets the request finish after the page has gone, for the last events when a tab is closed.
   *  Browsers cap the body at 64 KB, so it is for events only, never for a chunk. */
  keepalive?: boolean
}

export async function api<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const token = isStaffPath(path) ? (getStaff()?.token ?? null) : getAccessToken()

  const headers: Record<string, string> = { ...options.headers }
  let body: string | Blob | undefined
  if (options.bytes !== undefined) {
    headers['Content-Type'] = 'application/octet-stream'
    body = options.bytes
  } else if (options.body !== undefined) {
    headers['Content-Type'] = 'application/json'
    body = JSON.stringify(options.body)
  }
  if (token) headers.Authorization = `Bearer ${token}`

  const response = await fetch(path, {
    method: options.method ?? 'GET',
    headers,
    body,
    keepalive: options.keepalive,
  })
  if (response.status === 204) return undefined as T

  const data = (await response.json().catch(() => ({}))) as Record<string, unknown>
  if (!response.ok) {
    const code = typeof data.code === 'string' ? data.code : 'unknown'
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

/** How many chunks the recorder made. Say it again after the last flush if it changed. */
export interface FinishRequest {
  chunks_total?: number
}

// ---- the action log, the heartbeat, video chunks and resume (backend/app/schemas/recording.py)

export interface EventIn {
  client_seq: number
  type: string
  /** How long ago the page saw it. The server subtracts this from its own receive time. */
  age_ms: number
  payload?: Record<string, unknown>
}

export interface EventsResponse {
  accepted: number
  duplicates: number
  rejected: number
}

export interface HeartbeatResponse {
  server_time: string
  remaining_s: number
  status: SessionStatus
}

export interface ChunkResponse {
  status: 'stored' | 'duplicate'
}

export interface ResumeResponse {
  session_id: string
  /** Upload-only: chunks, events and complaints, for 48 hours after the test finished. */
  access_token: string
  status: 'finished'
  expires_at: string
}

// ---- pre-check, upload status and complaints (D6 and D8)

export interface PrecheckRequest {
  camera_ok: boolean
  mic_ok: boolean
  /** The candidate ticked "I have turned off notifications". A page cannot read the system's
   *  notification settings, so this is the candidate's own confirmation, kept for the reviewer. */
  notifications_off_confirmed: boolean
  /** Whether the browser was in full screen when the candidate left the pre-check. */
  fullscreen_ok: boolean
  browser: { name: string; version: string }
  /** False when the microphone step was left out (testing). `mic_ok` is then false and means
   *  "not checked", never "failed", so a reviewer can tell the two apart. */
  mic_checked?: boolean
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
      // "recording" means the camera check passed but no video has reached the server yet. The
      // pre-check cannot fix that, so the page that asked stays put and waits.
      return error.body.reason === 'recording' ? null : '/precheck'
    case 'not_started':
      return '/integrity'
    case 'finished':
    case 'time_up':
      return '/done'
    case 'unauthorized':
      return CANDIDATE_PATH
    default:
      return null
  }
}

/**
 * What a staff member should do after a failed request: sign in again, go back to their own
 * pages, or nothing (any other error is the screen's to show).
 */
export function staffRecovery(error: unknown): 'sign-in' | 'home' | null {
  if (!(error instanceof ApiError)) return null
  if (error.code === 'unauthorized' || error.code === 'invalid_credentials') return 'sign-in'
  if (error.code === 'forbidden') return 'home'
  return null
}
