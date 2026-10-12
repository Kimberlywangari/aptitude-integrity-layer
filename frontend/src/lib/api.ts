import { getAccessToken } from './session'

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
  const headers: Record<string, string> = {}
  let body: string | undefined
  if (options.body !== undefined) {
    headers['Content-Type'] = 'application/json'
    body = JSON.stringify(options.body)
  }
  const token = getAccessToken()
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

/**
 * Where a candidate belongs after one of the flow's "you are in the wrong place" errors, or
 * null when the error is something else. Keeps every screen's recovery rule in one place.
 */
export function pathForError(error: unknown): string | null {
  if (!(error instanceof ApiError)) return null
  switch (error.code) {
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
