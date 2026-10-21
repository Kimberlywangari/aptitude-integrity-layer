// In-memory stand-in for the server, for the screen tests only (tests/helpers/mockedApi.ts routes
// api() here). The app itself no longer imports it: every screen talks to the real server.
//
// Sign in with any email and password. An email starting with "admin" gets the admin role.
// The password "wrong" is refused, so the error path can be seen.

import type {
  AdminSitting,
  CloseSittingResponse,
  CreateSittingRequest,
  ImportReport,
  ImportRequest,
  Invite,
  InvitesResponse,
  QuestionBankSummary,
  RetireResponse,
} from '../adminTypes'
import { ApiError } from '../api'
import type {
  ComplaintRequest,
  ManifestResponse,
  PrecheckRequest,
  PrecheckResponse,
} from '../api'
import { getStaff } from '../staffSession'
import { MIN_REASON_CHARS } from '../reviewTypes'
import type {
  AuditEntry,
  DecisionOutcome,
  DecisionRequest,
  LoginResponse,
  QueueResponse,
} from '../reviewTypes'
import { buildDetail, buildQueue, initialState, SITTINGS } from './data'
import type { MockState } from './data'
import { runImport } from './importer'

const OUTCOMES: DecisionOutcome[] = ['no_concern', 'concern_noted', 'refer_for_follow_up']
const CODE_ALPHABET = '0123456789ABCDEFGHJKMNPQRSTVWXYZ'

let latencyMs = 120
let state: MockState
let sittings: AdminSitting[]
let bank: { section: string; cytonn: number; synthetic: number }[]
let nextCandidate: number
let complaintCount: number
let manifestCalls: Map<string, number>

function reset(): void {
  state = initialState()
  sittings = [
    {
      id: 1,
      name: 'Synthetic sitting 1',
      opens_at: null,
      closes_at: null,
      duration_s: 1800,
      question_count: 12,
      status: 'open',
      counts: { finished: 14, in_progress: 2, not_started: 4 },
    },
    {
      id: 2,
      name: 'Earlier synthetic sitting',
      opens_at: '2026-10-08T09:00:00Z',
      closes_at: '2026-10-08T11:00:00Z',
      duration_s: 1800,
      question_count: 12,
      status: 'closed',
      counts: { finished: 12, in_progress: 0, not_started: 0 },
    },
  ]
  bank = [
    { section: 'numerical', cytonn: 0, synthetic: 20 },
    { section: 'verbal', cytonn: 0, synthetic: 20 },
    { section: 'logical', cytonn: 0, synthetic: 20 },
  ]
  nextCandidate = 21
  complaintCount = 0
  manifestCalls = new Map()
}
reset()

/** Tests call these; the app does not. */
export function resetMock(): void {
  reset()
}
export function setMockLatency(ms: number): void {
  latencyMs = ms
}

// ---- helpers

function fail(status: number, code: string, extra: Record<string, unknown> = {}): never {
  throw new ApiError(status, code, { code, ...extra })
}

function bodyOf<T>(body: unknown): T {
  return (body ?? {}) as T
}

interface Identity {
  email: string
  role: 'reviewer' | 'admin'
}

/**
 * Who a staff token belongs to. Mock sign-in tokens spell it out; a token from the real server
 * (login is real while the rest of /api/review is still mocked) is matched to the stored session.
 */
function identityOf(token: string | null): Identity {
  if (!token || token.startsWith('mock-expired')) fail(401, 'unauthorized') // expired, for tests
  const mock = token.match(/^mock-(reviewer|admin):(.*)$/)
  if (mock) return { role: mock[1] as Identity['role'], email: mock[2] }
  const staff = getStaff()
  if (staff && staff.token === token) return { email: staff.email, role: staff.role }
  fail(401, 'unauthorized')
}

function emailOf(token: string): string {
  return identityOf(token).email
}

function audit(reviewer: string, action: AuditEntry['action'], candidate: string | null, detail: string) {
  state.audit.unshift({
    id: `A${state.audit.length + 1}`,
    ts: new Date().toISOString(),
    reviewer,
    action,
    candidate_id: candidate,
    detail,
  })
}

function bankSummary(): QuestionBankSummary {
  const by_section = bank.map((b) => ({ ...b, count: b.cytonn + b.synthetic }))
  return {
    total: by_section.reduce((n, s) => n + s.count, 0),
    cytonn: bank.reduce((n, s) => n + s.cytonn, 0),
    synthetic: bank.reduce((n, s) => n + s.synthetic, 0),
    by_section,
  }
}

function randomCode(): string {
  const bytes = new Uint8Array(8)
  crypto.getRandomValues(bytes)
  return Array.from(bytes, (b) => CODE_ALPHABET[b % CODE_ALPHABET.length]).join('')
}

// ---- router

export async function mockApi<T>(
  path: string,
  method: string,
  body: unknown,
  token: string | null,
): Promise<T> {
  if (latencyMs > 0) await new Promise((resolve) => setTimeout(resolve, latencyMs))
  const url = new URL(path, 'http://mock.local')
  const route = `${method} ${url.pathname}`
  const result = dispatch(route, url, body, token)
  return result as T
}

function requireStaff(token: string | null): string {
  identityOf(token)
  return token as string
}

function requireAdmin(token: string | null): string {
  const t = requireStaff(token)
  if (identityOf(t).role !== 'admin') fail(403, 'forbidden')
  return t
}

function dispatch(route: string, url: URL, body: unknown, token: string | null): unknown {
  let m: RegExpMatchArray | null

  // ---- candidate side
  if (route === 'POST /api/precheck/result') {
    const b = bodyOf<PrecheckRequest>(body)
    // The microphone is waived only when its step was left out, never when it failed.
    const micFine = b.mic_ok || b.mic_checked === false
    return { passed: Boolean(b.camera_ok && micFine) } satisfies PrecheckResponse
  }

  if (route === 'POST /api/complaints') {
    const b = bodyOf<ComplaintRequest>(body)
    const text = (b.text ?? '').trim()
    if (!['camera', 'upload', 'other'].includes(b.category) || !text || text.length > 1000) {
      fail(422, 'invalid_complaint')
    }
    complaintCount++
    return undefined
  }

  if ((m = route.match(/^GET \/api\/chunks\/([^/]+)\/manifest$/))) {
    const calls = (manifestCalls.get(m[1]) ?? 0) + 1
    manifestCalls.set(m[1], calls)
    const expected = 42
    const received = Math.min(expected, calls * 9)
    return {
      expected,
      received,
      missing: expected - received,
      bytes: received * 280_000,
      complete: received >= expected,
    } satisfies ManifestResponse
  }

  // ---- reviewer
  if (route === 'POST /api/review/login') {
    const b = bodyOf<{ email?: string; password?: string }>(body)
    const email = (b.email ?? '').trim()
    if (!email || !b.password || b.password === 'wrong') fail(401, 'invalid_credentials')
    const role = email.toLowerCase().startsWith('admin') ? 'admin' : 'reviewer'
    audit(email, 'login', null, 'signed in')
    return { token: `mock-${role}:${email}`, email, role } satisfies LoginResponse
  }

  if (route === 'GET /api/review/queue') {
    requireStaff(token)
    const requested = Number(url.searchParams.get('sitting') ?? SITTINGS[0].id)
    const sittingId = SITTINGS.some((s) => s.id === requested) ? requested : SITTINGS[0].id
    return {
      sittings: SITTINGS,
      sitting_id: sittingId,
      items: buildQueue(sittingId, state),
    } satisfies QueueResponse
  }

  if ((m = route.match(/^GET \/api\/review\/candidates\/([^/]+)$/))) {
    requireStaff(token)
    return buildDetail(m[1], state) ?? fail(404, 'candidate_not_found')
  }

  if ((m = route.match(/^POST \/api\/review\/candidates\/([^/]+)\/shortlist$/))) {
    const t = requireStaff(token)
    if (!buildDetail(m[1], state)) fail(404, 'candidate_not_found')
    const now = !state.shortlisted.has(m[1])
    if (now) state.shortlisted.add(m[1])
    else state.shortlisted.delete(m[1])
    audit(emailOf(t), 'decision', m[1], now ? 'shortlisted' : 'removed from shortlist')
    return { shortlisted: now }
  }

  if ((m = route.match(/^POST \/api\/review\/candidates\/([^/]+)\/video-view$/))) {
    const t = requireStaff(token)
    const b = bodyOf<{ flag_id?: string }>(body)
    audit(emailOf(t), 'video_view', m[1], b.flag_id ? `jumped to ${b.flag_id}` : 'opened video')
    return undefined
  }

  if (route === 'POST /api/review/decisions') {
    const t = requireStaff(token)
    const b = bodyOf<DecisionRequest>(body)
    if (!OUTCOMES.includes(b.outcome)) fail(422, 'invalid_outcome')
    if ((b.reason ?? '').trim().length < MIN_REASON_CHARS) fail(422, 'reason_too_short')
    const candidate = b.session_id?.replace(/^sess-/, '')
    if (!candidate || !buildDetail(candidate, state)) fail(404, 'candidate_not_found')
    const list = state.decisions.get(candidate) ?? []
    list.push({
      outcome: b.outcome,
      reason: b.reason.trim(),
      reviewer: emailOf(t),
      decided_at: new Date().toISOString(),
    })
    state.decisions.set(candidate, list)
    audit(emailOf(t), 'decision', candidate, b.outcome)
    return { decided_at: list[list.length - 1].decided_at }
  }

  if (route === 'GET /api/review/audit') {
    requireStaff(token)
    return { entries: state.audit }
  }

  // ---- admin
  if (route === 'GET /api/admin/sittings') {
    requireAdmin(token)
    return { sittings }
  }

  if (route === 'POST /api/admin/sittings') {
    const t = requireAdmin(token)
    const b = bodyOf<CreateSittingRequest>(body)
    if (!b.name?.trim()) fail(422, 'name_required')
    if (!(b.duration_s >= 60)) fail(422, 'invalid_duration')
    if (!(b.question_count >= 1)) fail(422, 'invalid_question_count')
    const available = bankSummary().total
    if (b.question_count > available) fail(409, 'question_bank_too_small', { available })
    if (sittings.some((s) => s.name === b.name.trim())) fail(409, 'name_taken')
    const sitting: AdminSitting = {
      id: Math.max(...sittings.map((s) => s.id)) + 1,
      name: b.name.trim(),
      opens_at: b.opens_at,
      closes_at: b.closes_at,
      duration_s: b.duration_s,
      question_count: b.question_count,
      status: 'open',
      counts: { finished: 0, in_progress: 0, not_started: 0 },
    }
    sittings.unshift(sitting)
    audit(emailOf(t), 'admin', null, `created sitting "${sitting.name}"`)
    return sitting
  }

  if ((m = route.match(/^POST \/api\/admin\/sittings\/(\d+)\/close$/))) {
    const t = requireAdmin(token)
    const sitting = sittings.find((s) => s.id === Number(m![1]))
    if (!sitting) fail(404, 'sitting_not_found')
    const force = Boolean(bodyOf<{ force?: boolean }>(body).force)
    const unfinished = sitting.counts.in_progress + sitting.counts.not_started
    if (sitting.status === 'closed') fail(409, 'already_closed')
    if (unfinished > 0 && !force) fail(409, 'sessions_unfinished', { unfinished })
    sitting.status = 'closed'
    audit(emailOf(t), 'admin', null, `closed sitting "${sitting.name}"${force ? ' (forced)' : ''}`)
    return { status: 'closed', forced: force } satisfies CloseSittingResponse
  }

  if (route === 'POST /api/admin/invites') {
    const t = requireAdmin(token)
    const count = Math.floor(Number(bodyOf<{ count?: number }>(body).count))
    if (!(count >= 1 && count <= 500)) fail(422, 'invalid_count')
    const invites: Invite[] = Array.from({ length: count }, () => ({
      candidate_id: `cand-${String(nextCandidate++).padStart(3, '0')}`,
      code: randomCode(),
    }))
    audit(emailOf(t), 'admin', null, `generated ${count} invitations`)
    return { invites } satisfies InvitesResponse
  }

  if (route === 'GET /api/admin/questions/summary') {
    requireAdmin(token)
    return bankSummary()
  }

  if (route === 'POST /api/admin/questions/import') {
    const t = requireAdmin(token)
    if (sittings.some((s) => s.status === 'open')) fail(409, 'sitting_open')
    const b = bodyOf<ImportRequest>(body)
    const outcome = runImport(b.filename ?? 'summary.csv', b.summary_csv ?? '', Boolean(b.bank_csv))
    if (!outcome.ok) fail(422, 'missing_columns', { columns: outcome.missing })
    for (const row of outcome.imported) {
      const key = row.section.toLowerCase()
      const section = bank.find((s) => s.section === key)
      if (section) section.cytonn++
      else bank.push({ section: key, cytonn: 1, synthetic: 0 })
    }
    audit(emailOf(t), 'admin', null, `imported ${outcome.report.imported} questions`)
    return outcome.report satisfies ImportReport
  }

  if (route === 'POST /api/admin/questions/retire-synthetic') {
    const t = requireAdmin(token)
    if (sittings.some((s) => s.status === 'open')) fail(409, 'sitting_open')
    const removed = bank.reduce((n, s) => n + s.synthetic, 0)
    for (const section of bank) section.synthetic = 0
    bank = bank.filter((s) => s.cytonn > 0)
    audit(emailOf(t), 'admin', null, `removed ${removed} synthetic questions`)
    return { removed, kept: 0 } satisfies RetireResponse
  }

  return fail(404, 'not_found', { route })
}

export function mockComplaintCount(): number {
  return complaintCount
}
