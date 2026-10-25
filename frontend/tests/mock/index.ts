// In-memory stand-in for the server, for the screen tests only (tests/helpers/mockedApi.ts routes
// api() here). The app itself no longer imports it: every screen talks to the real server.
//
// Sign in with any email and password. An email starting with "admin" gets the admin role.
// The password "wrong" is refused, so the error path can be seen.

import type {
  AdminSitting,
  AiSample,
  AiStatus,
  CloseSittingResponse,
  CreateSittingRequest,
  DeleteSittingResponse,
  ImportReport,
  ImportRequest,
  Invite,
  InviteListResponse,
  InvitesResponse,
  InviteStatus,
  MailStatus,
  PassMarkPreview,
  PreviewList,
  QuestionBankSummary,
  QuestionListResponse,
  QuestionRow,
  ResultsPlan,
  RetireResponse,
  SittingCandidate,
  SittingDetail,
} from '../../src/lib/adminTypes'
import { ApiError } from '../../src/lib/api'
import type {
  ComplaintRequest,
  ManifestResponse,
  PrecheckRequest,
  PrecheckResponse,
} from '../../src/lib/api'
import { getStaff } from '../../src/lib/staffSession'
import { MIN_REASON_CHARS } from '../../src/lib/reviewTypes'
import type {
  AuditEntry,
  BulkPassResponse,
  CandidatesResponse,
  DecisionOutcome,
  DecisionRequest,
  EmailState,
  LoginResponse,
  OutcomeItem,
  OutcomesResponse,
  OutcomeStatus,
  OverviewResponse,
  QueueResponse,
  ResultRequest,
} from '../../src/lib/reviewTypes'
import {
  buildActionLog,
  buildCandidates,
  buildDetail,
  buildOverview,
  buildQueue,
  buildResult,
  initialState,
  outcomeStatus,
  QUESTION_TOTAL,
  scoreOf,
  SITTINGS,
} from './data'
import type { MockState } from './data'
import { runImport } from './importer'

const OUTCOMES: DecisionOutcome[] = ['no_concern', 'concern_noted', 'refer_for_follow_up']
const CODE_ALPHABET = '0123456789ABCDEFGHJKMNPQRSTVWXYZ'

let latencyMs = 120

/** What the question-writer screens see. A test can flip `available` to see the other path. */
export const AI_STATUS: AiStatus = {
  provider: 'ollama',
  model: 'qwen2.5:7b',
  available: true,
  detail: 'Ollama (qwen2.5:7b).',
  max_per_category: 30,
  max_total: 100,
  categories: [
    ['numerical', 'Numerical'],
    ['verbal', 'Verbal'],
    ['logical', 'Logical'],
    ['critical thinking', 'Critical Thinking'],
    ['error checking', 'Error Checking'],
    ['ai competence', 'AI Competence'],
    ['office assistant', 'Office Assistant'],
  ].map(([key, label]) => ({ key, label, brief: `What ${label} questions are.` })),
}
let state: MockState
let sittings: AdminSitting[]
let bank: { section: string; cytonn: number; synthetic: number }[]
let nextCandidate: number
/** An invitee, with what only a sitting's own page shows. */
type Invitee = InviteStatus & {
  email_full?: string
  answered?: number
  paper?: Pick<SittingCandidate, 'paper_status' | 'paper_error' | 'waited_s'>
}
let invitees: Invitee[]
let mailStatus: MailStatus
let mailTestFails: boolean
let emailed: Set<string> // candidates who have been sent a result email
let resultsState: Omit<
  ResultsPlan,
  'sitting_closed' | 'pass_mark' | 'preview_passed' | 'preview_not_passed' | 'preview_not_passed_review'
>
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
      blueprint: null,
      question_mode: 'practice',
      status: 'open',
      pass_mark: null,
      counts: { finished: 14, in_progress: 2, not_started: 4, papers_pending: 0, papers_failed: 0 },
    },
    {
      id: 2,
      name: 'Earlier synthetic sitting',
      opens_at: '2026-10-08T09:00:00Z',
      closes_at: '2026-10-08T11:00:00Z',
      duration_s: 1800,
      question_count: 12,
      blueprint: null,
      question_mode: 'practice',
      status: 'closed',
      pass_mark: null,
      counts: { finished: 12, in_progress: 0, not_started: 0, papers_pending: 0, papers_failed: 0 },
    },
  ]
  bank = [
    { section: 'numerical', cytonn: 0, synthetic: 20 },
    { section: 'verbal', cytonn: 0, synthetic: 20 },
    { section: 'logical', cytonn: 0, synthetic: 20 },
  ]
  nextCandidate = 21
  // twenty invited, matching the first sitting's counts: 14 finished, 2 sitting now, 4 not opened
  invitees = Array.from({ length: 20 }, (_, i) => ({
    candidate_id: `cand-${String(i + 1).padStart(3, '0')}`,
    status: i < 14 ? 'finished' : i < 16 ? 'started' : 'not_opened',
    sitting_id: 1,
    sitting_name: 'Synthetic sitting 1',
  }))
  mailStatus = { set_up: true, from_address: 'm***@example.test', queued: 0, sent: 0, failed: 0 }
  mailTestFails = false
  emailed = new Set()
  resultsState = {
    sent_passed: 3,
    sent_not_passed: 1,
    queued: 0,
    failed: 0,
    held_back: ['cand-007'],
    did_not_finish: 2,
    without_email: 0,
  }
  complaintCount = 0
  manifestCalls = new Map()
}
reset()

/** A small stand-in for the server's list reader: `name, email` per line, a bad line is a problem. */
function readMockList(text: string, already: Set<string>) {
  const people: PreviewList['people'] = []
  const problems: PreviewList['problems'] = []
  const seen = new Set<string>()
  text.split(/\r?\n/).forEach((raw, i) => {
    const line = raw.trim()
    if (!line) return
    const [name, email = ''] = line.split(',').map((x) => x.trim())
    const address = email.toLowerCase()
    if (!/^[^@\s]+@[^@\s]+\.[^@\s]{2,}$/.test(address)) problems.push({ line: i + 1, reason: 'bad_email', text: line })
    else if (!name) problems.push({ line: i + 1, reason: 'name_missing', text: line })
    else if (seen.has(address)) problems.push({ line: i + 1, reason: 'repeated', text: line })
    else if (already.has(address)) problems.push({ line: i + 1, reason: 'already_invited', text: line })
    else {
      seen.add(address)
      people.push({ line: i + 1, name, email: address })
    }
  })
  return { people, problems }
}

/** Tests change what the mock says about the mail set-up. */
export function setMockMail(patch: Partial<MailStatus> & { testFails?: boolean }): void {
  const { testFails, ...rest } = patch
  mailStatus = { ...mailStatus, ...rest }
  if (testFails !== undefined) mailTestFails = testFails
}

/** Marks candidates as already sent a result email, for the reviewer's shortlist note. */
export function setMockEmailed(ids: string[]): void {
  emailed = new Set(ids)
}

/** Tests call these; the app does not. */
export function resetMock(): void {
  reset()
}
export function setMockLatency(ms: number): void {
  latencyMs = ms
}
/** Changes one invitee, for a test that needs someone waiting on an AI paper, say. */
export function patchMockInvitee(candidateId: string, patch: Partial<Invitee>): void {
  const found = invitees.find((i) => i.candidate_id === candidateId)
  if (found) Object.assign(found, patch)
}
/** Cytonn's questions as loaded from their API (usable ones), beside the made-up bank. */
export function loadCytonnIntoMock(): void {
  const real: Record<string, number> = {
    verbal: 550,
    numerical: 563,
    logical: 250,
    'critical thinking': 235,
    'error checking': 98,
    'ai competence': 26,
    'office assistant': 12,
  }
  const made = new Map(bank.map((b) => [b.section, b.synthetic]))
  bank = Object.entries(real).map(([section, cytonn]) => ({
    section,
    cytonn,
    synthetic: made.get(section) ?? 0,
  }))
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
  // in name order, as the server lists them
  const by_section = bank
    .map((b) => ({ ...b, count: b.cytonn + b.synthetic }))
    .sort((a, b) => a.section.localeCompare(b.section))
  return {
    total: by_section.reduce((n, s) => n + s.count, 0),
    cytonn: bank.reduce((n, s) => n + s.cytonn, 0),
    synthetic: bank.reduce((n, s) => n + s.synthetic, 0),
    by_section,
  }
}

/** One row per question the bank summary counts: the real ones first in each section. */
function questionRows(): QuestionRow[] {
  const difficulties = ['easy', 'medium', 'hard'] as const
  const rows: QuestionRow[] = []
  let number = 1
  for (const section of [...bank].sort((a, b) => a.section.localeCompare(b.section))) {
    for (let i = 0; i < section.cytonn + section.synthetic; i++, number++) {
      const real = i < section.cytonn
      rows.push({
        id: real ? `C${number}` : `Q${String(number).padStart(3, '0')}`,
        section: section.section,
        difficulty: real ? null : difficulties[i % 3],
        source: real ? 'cytonn' : 'synthetic',
        preview: `${real ? 'A Cytonn' : 'A placeholder'} ${section.section} question, number ${i + 1}`,
        pct_correct: real ? 40 + (i % 5) * 10 : null,
        n: real ? 800 : null,
      })
    }
  }
  return rows
}

function randomCode(): string {
  const bytes = new Uint8Array(8)
  crypto.getRandomValues(bytes)
  return Array.from(bytes, (b) => CODE_ALPHABET[b % CODE_ALPHABET.length]).join('')
}

// ---- router

/** One person's result, with the checks the server makes. Throws the server's error codes. */
function recordResult(id: string, request: ResultRequest, by: string): void {
  const panel = buildResult(id, state)
  if (panel.blocked_by) fail(409, panel.blocked_by)
  if (request.result !== 'pass' && request.result !== 'fail') fail(422, 'invalid_result')
  let reason: string | null = null
  if (request.result === 'fail') {
    const known = panel.reasons.find((r) => r.key === request.reason_key)
    const custom = request.reason_key === undefined || request.reason_key === null || request.reason_key === 'other'
    if (!known && !custom) fail(422, 'invalid_reason')
    reason = known ? known.text : (request.reason_text ?? '').trim()
    if (!reason) fail(422, 'reason_required')
    if (reason.length > 200) fail(422, 'reason_too_long', { max: 200 })
  }
  state.results.set(id, {
    result: request.result,
    basis: 'review',
    reason,
    by,
    at: new Date().toISOString(),
    emailState: 'queued',
    appeal: false,
  })
  audit(by, 'decision', id, `${request.result} email queued`)
}

const PAGE_SIZE = 50
const ALL_STATUSES: OutcomeStatus[] = [
  'invited',
  'in_progress',
  'waiting_review',
  'in_review',
  'ready',
  'passed',
  'failed_score',
  'failed_review',
  'under_appeal',
  'incomplete',
]
const ALL_EMAIL: EmailState[] = ['none', 'queued', 'sent', 'failed']

/** The outcomes list the way the server builds it: counts over the whole sitting, then a page. */
function outcomesFor(url: URL, admin: boolean): OutcomesResponse {
  const requested = Number(url.searchParams.get('sitting') ?? SITTINGS[0].id)
  const sittingId = SITTINGS.some((s) => s.id === requested) ? requested : SITTINGS[0].id
  const status = url.searchParams.get('status')
  const email = url.searchParams.get('email')
  if (status && !ALL_STATUSES.includes(status as OutcomeStatus)) fail(422, 'invalid_status')
  if (email && !ALL_EMAIL.includes(email as EmailState)) fail(422, 'invalid_email_state')
  const needle = (url.searchParams.get('q') ?? '').trim().toLowerCase()
  const page = Math.max(1, Number(url.searchParams.get('page') ?? 1))
  const rows = buildCandidates(sittingId, state).map((row) => {
    const panel = buildResult(row.candidate_id, state)
    const finished = row.status === 'finished'
    const item: OutcomeItem = {
      candidate_id: row.candidate_id,
      status: outcomeStatus(row.candidate_id, state),
      score: finished ? scoreOf(row.candidate_id) : null,
      total: finished ? QUESTION_TOTAL : null,
      flag_count: row.flag_count,
      email_state: panel.email_state,
      has_email: true,
      result_at: panel.decided_at,
      can_mark_passed: false,
    }
    item.can_mark_passed =
      (item.status === 'ready' || item.status === 'in_review') && item.email_state === 'none'
    if (admin) {
      item.name = `Person ${row.candidate_id.replace(/\D/g, '')}`
      item.email = 'p***@example.test'
    }
    return item
  })
  const counts = Object.fromEntries(ALL_STATUSES.map((k) => [k, 0])) as Record<OutcomeStatus, number>
  const emailCounts = Object.fromEntries(ALL_EMAIL.map((k) => [k, 0])) as Record<EmailState, number>
  for (const item of rows) {
    counts[item.status] += 1
    emailCounts[item.email_state] += 1
  }
  const matching = rows.filter(
    (i) =>
      (!status || i.status === status) &&
      (!email || i.email_state === email) &&
      (!needle || i.candidate_id.includes(needle)),
  )
  return {
    sittings: SITTINGS,
    sitting_id: sittingId,
    pass_mark: sittingId === 1 ? state.passMark : null,
    question_count: QUESTION_TOTAL,
    sitting_closed: sittings.find((s) => s.id === sittingId)?.status === 'closed',
    counts,
    email_counts: emailCounts,
    total: rows.length,
    matching: matching.length,
    page,
    page_size: PAGE_SIZE,
    items: matching.slice((page - 1) * PAGE_SIZE, page * PAGE_SIZE),
  }
}

/** How many would newly fall below `value`, and how many would stop being below it. */
function previewMark(sitting: AdminSitting, value: number | null): PassMarkPreview {
  const current = sitting.pass_mark ?? null
  let newly = 0
  let cleared = 0
  if (sitting.id === 1) {
    for (const row of buildCandidates(1, state)) {
      if (row.status !== 'finished' || state.results.has(row.candidate_id)) continue
      const score = scoreOf(row.candidate_id)
      const was = current !== null && score < current
      const will = value !== null && score < value
      if (will && !was) newly += 1
      if (was && !will) cleared += 1
    }
  }
  const closed = sitting.status === 'closed'
  return {
    current,
    value,
    newly_below: newly,
    no_longer_below: cleared,
    sitting_closed: closed,
    emails_now: closed ? newly : 0,
  }
}

/**
 * The server's document reader, in a few lines: it reads the file as text, and a file whose first
 * words are a code word makes the error the real one would. A table is asked for as CSV.
 */
async function extractText(url: URL, body: unknown, token: string | null) {
  requireAdmin(token)
  const text = body instanceof Blob ? await body.text() : String(body ?? '')
  const want = url.searchParams.get('want') === 'table' ? 'table' : 'text'
  if (!text.trim()) fail(422, 'empty_file')
  if (text.startsWith('LEGACY')) fail(415, 'legacy_office_format')
  if (text.startsWith('SCANNED')) fail(422, 'scanned_pdf')
  if (text.startsWith('LOCKED')) fail(422, 'password_protected')
  if (want === 'table' && !text.includes(',')) fail(422, 'no_table_found')
  // a stand-in for a spreadsheet: its words come back as the comma-separated rows the server makes
  const kind = text.startsWith('SHEET:') ? 'xlsx' : 'text'
  return { text: kind === 'xlsx' ? text.slice('SHEET:'.length) : text, kind }
}

export async function mockApi<T>(
  path: string,
  method: string,
  body: unknown,
  token: string | null,
): Promise<T> {
  if (latencyMs > 0) await new Promise((resolve) => setTimeout(resolve, latencyMs))
  const url = new URL(path, 'http://mock.local')
  const route = `${method} ${url.pathname}`
  if (route === 'POST /api/admin/extract-text') return (await extractText(url, body, token)) as T
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

  if (route === 'GET /api/review/candidates') {
    requireStaff(token)
    const requested = Number(url.searchParams.get('sitting') ?? SITTINGS[0].id)
    const sittingId = SITTINGS.some((s) => s.id === requested) ? requested : SITTINGS[0].id
    return {
      sittings: SITTINGS,
      sitting_id: sittingId,
      items: buildCandidates(sittingId, state),
    } satisfies CandidatesResponse
  }

  if (route === 'GET /api/review/outcomes') {
    requireStaff(token)
    return outcomesFor(url, false)
  }

  if ((m = route.match(/^POST \/api\/review\/candidates\/([^/]+)\/result$/))) {
    const t = requireStaff(token)
    if (!buildDetail(m[1], state)) fail(404, 'candidate_not_found')
    recordResult(m[1], bodyOf<ResultRequest>(body), emailOf(t))
    return { status: state.results.get(m[1])!.result === 'pass' ? 'passed' : 'failed_review' }
  }

  if ((m = route.match(/^POST \/api\/review\/candidates\/([^/]+)\/result\/resend$/))) {
    const t = requireStaff(token)
    if (!bodyOf<{ confirm?: boolean }>(body).confirm) fail(422, 'confirmation_required')
    const stored = state.results.get(m[1])
    if (!stored) fail(409, 'no_result')
    stored!.emailState = 'queued'
    audit(emailOf(t), 'decision', m[1], `${stored!.result} email sent again`)
    return undefined
  }

  if (route === 'POST /api/review/results/bulk-pass') {
    const t = requireStaff(token)
    const ids = [...new Set(bodyOf<{ candidate_ids?: string[] }>(body).candidate_ids ?? [])]
    const done: BulkPassResponse = { queued: 0, refused: [] }
    for (const id of ids) {
      try {
        if (!buildDetail(id, state)) fail(404, 'candidate_not_found')
        recordResult(id, { result: 'pass' }, emailOf(t))
        done.queued += 1
      } catch (error) {
        if (!(error instanceof ApiError)) throw error
        done.refused.push({ candidate_id: id, code: error.code })
      }
    }
    return done
  }

  if ((m = route.match(/^GET \/api\/review\/candidates\/([^/]+)\/events$/))) {
    requireStaff(token)
    return buildActionLog(m[1], state) ?? fail(404, 'candidate_not_found')
  }

  if (route === 'GET /api/review/overview') {
    requireStaff(token)
    const requested = Number(url.searchParams.get('sitting') ?? SITTINGS[0].id)
    const sittingId = SITTINGS.some((s) => s.id === requested) ? requested : SITTINGS[0].id
    return {
      sittings: SITTINGS,
      sitting_id: sittingId,
      sitting_status: sittings.find((s) => s.id === sittingId)?.status ?? null,
      ...buildOverview(sittingId, state),
    } satisfies OverviewResponse
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
    return { shortlisted: now, result_email_sent: emailed.has(m[1]) }
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

  if ((m = route.match(/^GET \/api\/admin\/sittings\/(\d+)$/))) {
    requireAdmin(token)
    const sitting = sittings.find((s) => s.id === Number(m![1]))
    if (!sitting) fail(404, 'sitting_not_found')
    const candidates = invitees
      .filter((i) => i.sitting_id === sitting.id)
      .sort((a, b) => a.candidate_id.localeCompare(b.candidate_id))
      .map((i): SittingCandidate => {
        const opened = i.status !== 'not_opened'
        const begun = i.status === 'started' || i.status === 'finished'
        return {
          candidate_id: i.candidate_id,
          state: i.status,
          answered:
            i.answered ??
            (i.status === 'finished' ? sitting.question_count : begun ? Math.floor(sitting.question_count / 2) : 0),
          paper_status: i.paper?.paper_status ?? (opened ? 'ready' : null),
          paper_error: i.paper?.paper_error ?? null,
          waited_s: i.paper?.waited_s ?? null,
          opened_at: opened ? '2026-10-20T09:00:00Z' : null,
          started_at: begun ? '2026-10-20T09:05:00Z' : null,
          finished_at: i.status === 'finished' ? '2026-10-20T09:35:00Z' : null,
          name: i.name ?? null,
          email: i.email ?? null,
          invite_mail: i.invite_mail ?? null,
        }
      })
    // a copy, as the wire would give: the page must not share objects with this stand-in
    return {
      sitting: { ...sitting, counts: { ...sitting.counts } },
      candidates,
    } satisfies SittingDetail
  }

  if ((m = route.match(/^POST \/api\/admin\/sittings\/(\d+)\/delete$/))) {
    const t = requireAdmin(token)
    const sitting = sittings.find((s) => s.id === Number(m![1]))
    if (!sitting) fail(404, 'sitting_not_found')
    const typed = bodyOf<{ confirm_name?: string }>(body).confirm_name ?? ''
    if (typed.trim() !== sitting.name) fail(422, 'name_does_not_match')
    if (sitting.counts.in_progress > 0) {
      fail(409, 'sessions_in_progress', { in_progress: sitting.counts.in_progress })
    }
    const mine = invitees.filter((i) => i.sitting_id === sitting.id)
    const sat = mine.filter((i) => i.status !== 'not_opened').length
    sittings = sittings.filter((s) => s.id !== sitting.id)
    invitees = invitees.filter((i) => i.sitting_id !== sitting.id)
    audit(emailOf(t), 'admin', null, `deleted sitting "${sitting.name}": ${sat} sessions, ${mine.length} candidates`)
    return {
      sessions: sat,
      candidates: mine.length,
      questions: sitting.question_mode === 'ai' ? sat * sitting.question_count : 0,
    } satisfies DeleteSittingResponse
  }

  if (route === 'POST /api/admin/sittings') {
    const t = requireAdmin(token)
    const b = bodyOf<CreateSittingRequest>(body)
    if (!b.name?.trim()) fail(422, 'name_required')
    const mode = b.question_mode ?? 'bank'
    const countOf = (s: { count: number; cytonn: number; synthetic: number }) =>
      mode === 'cytonn' ? s.cytonn : mode === 'practice' ? s.synthetic : s.count
    const inBank = new Map(
      bankSummary()
        .by_section.map((s) => [s.section, countOf(s)] as const)
        .filter(([, n]) => n > 0),
    )
    if (mode === 'cytonn' && inBank.size === 0) fail(409, 'cytonn_not_loaded')
    const blueprint = Object.fromEntries(
      Object.entries(b.per_section ?? {}).filter(([, n]) => n > 0),
    )
    const total = Object.values(blueprint).reduce((n, v) => n + v, 0)
    if (!(total >= 1)) fail(422, 'invalid_question_count')
    if (mode === 'ai') {
      if (!AI_STATUS.available) fail(503, 'question_writer_unavailable', { detail: AI_STATUS.detail })
      const kinds = new Set(AI_STATUS.categories.map((c) => c.key))
      const odd = Object.keys(blueprint).filter((key) => !kinds.has(key))
      if (odd.length) fail(422, 'unknown_section', { sections: odd })
      if (Object.values(blueprint).some((n) => n > AI_STATUS.max_per_category)) {
        fail(422, 'too_many_questions', { max_per_category: AI_STATUS.max_per_category })
      }
    } else {
      const unknown = Object.keys(blueprint).filter((section) => !inBank.has(section))
      if (unknown.length) fail(422, 'unknown_section', { sections: unknown })
      const short = Object.entries(blueprint)
        .filter(([section, n]) => (inBank.get(section) ?? 0) < n)
        .map(([section, needed]) => ({ section, available: inBank.get(section) ?? 0, needed }))
      if (short.length) fail(409, 'section_too_small', { sections: short })
    }
    if (sittings.some((s) => s.name === b.name.trim())) fail(409, 'name_taken')
    const sitting: AdminSitting = {
      id: Math.max(...sittings.map((s) => s.id)) + 1,
      name: b.name.trim(),
      opens_at: b.opens_at,
      closes_at: b.closes_at,
      duration_s: total * 105, // 1.75 minutes a question, as the server sets it
      question_count: total,
      blueprint,
      question_mode: mode,
      status: 'open',
      counts: { finished: 0, in_progress: 0, not_started: 0, papers_pending: 0, papers_failed: 0 },
    }
    sittings.unshift(sitting)
    audit(
      emailOf(t),
      'admin',
      null,
      `created sitting "${sitting.name}"${mode === 'ai' ? ' (questions written by AI)' : ''}`,
    )
    return sitting
  }

  if (route === 'GET /api/admin/ai-questions/status') {
    requireAdmin(token)
    return AI_STATUS
  }

  if (route === 'POST /api/admin/ai-questions/sample') {
    requireAdmin(token)
    const b = bodyOf<{ category: string; difficulty?: string }>(body)
    if (!AI_STATUS.available) fail(503, 'question_writer_unavailable', { detail: AI_STATUS.detail })
    if (!AI_STATUS.categories.some((c) => c.key === b.category)) {
      fail(422, 'unknown_section', { sections: [b.category] })
    }
    const sample: AiSample = {
      category: b.category,
      difficulty: b.difficulty ?? 'medium',
      text: 'A cyclist rides 36 km in 3 hours. What is the average speed in km per hour?',
      options: ['10', '12', '14', '9'],
      correct_index: 1,
      explanation: '36 / 3 = 12.',
      written_by: 'ollama:qwen2.5:7b',
      seconds: 41.5,
      rounds: 2,
      rejected: ['the independent check chose a different answer'],
    }
    return sample
  }

  if ((m = route.match(/^POST \/api\/admin\/sittings\/(\d+)\/retry-papers$/))) {
    requireAdmin(token)
    const sitting = sittings.find((s) => s.id === Number(m![1]))
    if (!sitting) fail(404, 'sitting_not_found')
    if (sitting.question_mode !== 'ai') fail(409, 'not_an_ai_sitting')
    const restarted = sitting.counts.papers_failed + sitting.counts.papers_pending
    sitting.counts.papers_pending = restarted
    sitting.counts.papers_failed = 0
    return { restarted }
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

  if (route === 'POST /api/admin/invites/preview') {
    requireAdmin(token)
    const asked = bodyOf<{ list_text: string; sitting_id?: number | null }>(body)
    const target = sittings.find((s) => s.id === asked.sitting_id) ?? sittings.find((s) => s.status === 'open')
    if (!target) fail(409, 'no_open_sitting')
    const read = readMockList(asked.list_text, new Set(invitees.map((i) => i.email_full ?? '')))
    return {
      people: read.people,
      problems: read.problems,
      sitting_id: target!.id,
      sitting_name: target!.name,
    } satisfies PreviewList
  }

  if (route === 'GET /api/admin/mail') {
    requireAdmin(token)
    return { ...mailStatus } satisfies MailStatus
  }

  if (route === 'POST /api/admin/mail/test') {
    requireAdmin(token)
    if (!mailStatus.set_up) fail(409, 'mail_not_set_up')
    if (mailTestFails) fail(502, 'mail_failed', { detail: 'SMTPAuthenticationError: 535 not accepted' })
    return { sent: true }
  }

  if (route === 'POST /api/admin/mail/retry') {
    requireAdmin(token)
    const requeued = mailStatus.failed
    mailStatus.queued += requeued
    mailStatus.failed = 0
    return { requeued }
  }

  if ((m = route.match(/^GET \/api\/admin\/sittings\/(\d+)\/results$/))) {
    requireAdmin(token)
    const sitting = sittings.find((s) => s.id === Number(m![1]))
    if (!sitting) fail(404, 'sitting_not_found')
    return {
      sitting_closed: sitting!.status === 'closed',
      pass_mark: sitting!.pass_mark ?? null,
      ...resultsState,
      preview_passed: {
        subject: 'Your Cytonn aptitude test result: you have passed',
        body: "Dear [candidate's name],\n\nYou passed.\n",
      },
      preview_not_passed: {
        subject: 'Your Cytonn aptitude test result',
        body: "Dear [candidate's name],\n\nNot this time.\n",
      },
      preview_not_passed_review: {
        subject: 'Your Cytonn aptitude test result',
        body: "Dear [candidate's name],\n\nA person looked at your sitting.\n",
      },
    } satisfies ResultsPlan
  }

  if ((m = route.match(/^GET \/api\/admin\/sittings\/(\d+)\/pass-mark\/preview$/))) {
    requireAdmin(token)
    const sitting = sittings.find((s) => s.id === Number(m![1]))
    if (!sitting) fail(404, 'sitting_not_found')
    const raw = url.searchParams.get('value')
    const value = raw === null || raw === '' ? null : Number(raw)
    if (value !== null && (!Number.isInteger(value) || value < 1 || value > sitting!.question_count)) {
      fail(422, 'invalid_pass_mark', { min: 1, max: sitting!.question_count })
    }
    return previewMark(sitting!, value)
  }

  if ((m = route.match(/^POST \/api\/admin\/sittings\/(\d+)\/pass-mark$/))) {
    const t = requireAdmin(token)
    const sitting = sittings.find((s) => s.id === Number(m![1]))
    if (!sitting) fail(404, 'sitting_not_found')
    const value = bodyOf<{ pass_mark?: number | null }>(body).pass_mark ?? null
    if (value !== null && (!Number.isInteger(value) || value < 1 || value > sitting!.question_count)) {
      fail(422, 'invalid_pass_mark', { min: 1, max: sitting!.question_count })
    }
    const preview = previewMark(sitting!, value)
    sitting!.pass_mark = value
    if (sitting!.id === 1) state.passMark = value
    const queued = sitting!.status === 'closed' ? preview.newly_below : 0
    audit(emailOf(t), 'admin', null, `pass mark of "${sitting!.name}" changed to ${value}`)
    return { pass_mark: value, queued }
  }

  if ((m = route.match(/^POST \/api\/admin\/candidates\/([^/]+)\/appeal$/))) {
    const t = requireAdmin(token)
    const stored = state.results.get(m[1])
    if (!stored || stored.result !== 'fail') fail(409, 'not_failed')
    stored!.appeal = bodyOf<{ under_appeal?: boolean }>(body).under_appeal === true
    audit(emailOf(t), 'decision', m[1], stored!.appeal ? 'marked under appeal' : 'appeal closed')
    return undefined
  }

  if (route === 'GET /api/admin/outcomes') {
    requireAdmin(token)
    return outcomesFor(url, true)
  }

  if (route === 'POST /api/admin/invites') {
    const t = requireAdmin(token)
    const asked = bodyOf<{ count?: number; list_text?: string; sitting_id?: number | null }>(body)
    if (typeof asked.list_text === 'string') {
      const read = readMockList(asked.list_text, new Set(invitees.map((i) => i.email_full ?? '')))
      if (read.problems.length || !read.people.length) {
        fail(422, 'list_has_problems', { problems: read.problems, found: read.people.length })
      }
      const open = sittings.filter((s) => s.status === 'open')
      const chosen = (sittings.find((s) => s.id === asked.sitting_id) ?? open[0]) as AdminSitting
      const made: Invite[] = read.people.map((p) => ({
        candidate_id: `cand-${String(nextCandidate++).padStart(3, '0')}`,
        code: randomCode(),
        name: p.name,
        email: p.email,
      }))
      for (const invite of made) {
        invitees.unshift({
          candidate_id: invite.candidate_id,
          status: 'not_opened',
          sitting_id: chosen.id,
          sitting_name: chosen.name,
          name: invite.name,
          email: `${invite.email!.slice(0, 1)}***${invite.email!.slice(invite.email!.indexOf('@'))}`,
          email_full: invite.email,
          invite_mail: 'queued',
        })
      }
      chosen.counts.not_started += made.length
      mailStatus.queued += made.length
      audit(emailOf(t), 'admin', null, `generated ${made.length} invitations for "${chosen.name}"`)
      return { invites: made, sitting_id: chosen.id, sitting_name: chosen.name } satisfies InvitesResponse
    }
    const count = Math.floor(Number(asked.count))
    if (!(count >= 1 && count <= 500)) fail(422, 'invalid_count')
    const open = sittings.filter((s) => s.status === 'open')
    let target: AdminSitting | undefined
    if (asked.sitting_id != null) {
      target = sittings.find((s) => s.id === asked.sitting_id)
      if (!target) fail(404, 'sitting_not_found')
      if (target.status !== 'open') fail(409, 'sitting_closed')
    } else {
      if (open.length === 0) fail(409, 'no_open_sitting')
      if (open.length > 1) fail(422, 'sitting_required', { sittings: open.map((s) => s.id) })
      target = open[0]
    }
    const chosen = target as AdminSitting
    const invites: Invite[] = Array.from({ length: count }, () => ({
      candidate_id: `cand-${String(nextCandidate++).padStart(3, '0')}`,
      code: randomCode(),
    }))
    for (const invite of invites) {
      invitees.unshift({
        candidate_id: invite.candidate_id,
        status: 'not_opened',
        sitting_id: chosen.id,
        sitting_name: chosen.name,
      })
    }
    chosen.counts.not_started += count
    audit(emailOf(t), 'admin', null, `generated ${count} invitations for "${chosen.name}"`)
    return {
      invites,
      sitting_id: chosen.id,
      sitting_name: chosen.name,
    } satisfies InvitesResponse
  }

  if (route === 'GET /api/admin/invites') {
    requireAdmin(token)
    const wanted = url.searchParams.get('sitting')
    const rows = wanted ? invitees.filter((i) => i.sitting_id === Number(wanted)) : invitees
    return { invites: rows.slice(0, 500), total: rows.length } satisfies InviteListResponse
  }

  if ((m = route.match(/^POST \/api\/admin\/invites\/([^/]+)\/reissue$/))) {
    const t = requireAdmin(token)
    if (!invitees.some((i) => i.candidate_id === m![1])) fail(404, 'candidate_not_found')
    audit(emailOf(t), 'admin', null, `issued a new code for ${m[1]}`)
    return { candidate_id: m[1], code: randomCode() } satisfies Invite
  }

  if (route === 'GET /api/admin/questions') {
    requireAdmin(token)
    const wanted = url.searchParams.get('section')
    const limit = Math.max(1, Math.min(500, Number(url.searchParams.get('limit') ?? 100)))
    const offset = Math.max(0, Number(url.searchParams.get('offset') ?? 0))
    const all = questionRows().filter((q) => !wanted || q.section === wanted)
    return {
      questions: all.slice(offset, offset + limit),
      total: all.length,
    } satisfies QuestionListResponse
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
