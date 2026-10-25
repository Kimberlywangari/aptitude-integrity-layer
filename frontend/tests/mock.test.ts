import { beforeEach, describe, expect, it } from 'vitest'
import { ApiError } from '../src/lib/api'
import type {
  AdminSitting,
  ImportReport,
  InviteListResponse,
  InvitesResponse,
  QuestionListResponse,
} from '../src/lib/adminTypes'
import { mockApi, resetMock, setMockLatency } from './mock'
import { clearStaff, saveStaff } from '../src/lib/staffSession'
import type { CandidateDetail, OverviewResponse, QueueResponse } from '../src/lib/reviewTypes'

const REVIEWER = 'mock-reviewer:r@example.com'
const ADMIN = 'mock-admin:admin@example.com'

const call = <T>(path: string, method = 'GET', body?: unknown, token: string | null = REVIEWER) =>
  mockApi<T>(path, method, body, token)

async function codeOf(promise: Promise<unknown>): Promise<string> {
  const error = await promise.then(
    () => null,
    (e: unknown) => e,
  )
  expect(error).toBeInstanceOf(ApiError)
  return (error as ApiError).code
}

beforeEach(() => {
  setMockLatency(0)
  resetMock()
})

describe('mock sign-in and access', () => {
  it('signs in with any email and gives an admin role to admin addresses', async () => {
    const reviewer = await call<{ role: string }>('/api/review/login', 'POST', {
      email: 'r@example.com',
      password: 'x',
    }, null)
    const admin = await call<{ role: string }>('/api/review/login', 'POST', {
      email: 'admin@example.com',
      password: 'x',
    }, null)
    expect(reviewer.role).toBe('reviewer')
    expect(admin.role).toBe('admin')
  })

  it('refuses the password "wrong"', async () => {
    const code = await codeOf(
      call('/api/review/login', 'POST', { email: 'r@example.com', password: 'wrong' }, null),
    )
    expect(code).toBe('invalid_credentials')
  })

  it('accepts a token from the real server when it is the stored session', async () => {
    saveStaff({ token: 'eyJ.real.token', email: 'real@example.com', role: 'reviewer' })
    try {
      await expect(call('/api/review/queue', 'GET', undefined, 'eyJ.real.token')).resolves.toBeTruthy()
      expect(await codeOf(call('/api/review/queue', 'GET', undefined, 'eyJ.someone.else'))).toBe(
        'unauthorized',
      )
      // the role of a real token is the stored session's
      expect(await codeOf(call('/api/admin/sittings', 'GET', undefined, 'eyJ.real.token'))).toBe(
        'forbidden',
      )
    } finally {
      clearStaff()
    }
  })

  it('refuses a token marked expired', async () => {
    expect(await codeOf(call('/api/review/queue', 'GET', undefined, 'mock-expired:r@example.com'))).toBe(
      'unauthorized',
    )
  })

  it('needs a token for review calls and an admin token for admin calls', async () => {
    expect(await codeOf(call('/api/review/queue', 'GET', undefined, null))).toBe('unauthorized')
    expect(await codeOf(call('/api/admin/sittings'))).toBe('forbidden')
    await expect(call('/api/admin/sittings', 'GET', undefined, ADMIN)).resolves.toBeTruthy()
  })
})

describe('mock review queue and decisions', () => {
  it('orders the queue by rank and keeps logging-only candidates in their own lane', async () => {
    const queue = await call<QueueResponse>('/api/review/queue')
    const ranks = queue.items.map((i) => i.rank)
    expect(ranks).toEqual([...ranks].sort((a, b) => a - b))
    const lane = queue.items.filter((i) => i.logging_only)
    expect(lane.map((i) => i.candidate_id)).toEqual(['cand-004'])
    expect(queue.items[queue.items.length - 1].logging_only).toBe(true)
    // candidate IDs only, never names
    expect(queue.items.every((i) => /^cand-\d{3}$/.test(i.candidate_id))).toBe(true)
  })

  it('gives an empty queue for a sitting that has not run', async () => {
    const queue = await call<QueueResponse>('/api/review/queue?sitting=2')
    expect(queue.sitting_id).toBe(2)
    expect(queue.items).toEqual([])
  })

  it('puts no video seek on a flag that falls in a recording gap', async () => {
    const detail = await call<CandidateDetail>('/api/review/candidates/cand-015')
    const inGap = detail.flags.find((f) => f.elapsed_s === 930)
    const before = detail.flags.find((f) => f.elapsed_s === 520)
    expect(inGap?.video_seek).toBeNull()
    expect(before?.video_seek).toEqual({ segment: 0, seek_s: 515 })
  })

  it('starts the video at most 5 s before the flag and never before zero', async () => {
    const detail = await call<CandidateDetail>('/api/review/candidates/cand-007')
    for (const flag of detail.flags) {
      expect(flag.video_seek?.seek_s).toBe(Math.max(0, flag.elapsed_s - 5))
    }
  })

  it('rejects a reason shorter than 20 characters and an unknown outcome', async () => {
    const body = { session_id: 'sess-cand-007', outcome: 'no_concern', reason: 'too short' }
    expect(await codeOf(call('/api/review/decisions', 'POST', body))).toBe('reason_too_short')
    expect(
      await codeOf(
        call('/api/review/decisions', 'POST', { ...body, outcome: 'reject', reason: 'x'.repeat(30) }),
      ),
    ).toBe('invalid_outcome')
  })

  it('records a decision, shows it on the candidate and in the queue, and audits it', async () => {
    await call('/api/review/decisions', 'POST', {
      session_id: 'sess-cand-007',
      outcome: 'concern_noted',
      reason: 'Copy attempt and a long hold on question 22 in the video.',
    })
    const detail = await call<CandidateDetail>('/api/review/candidates/cand-007')
    expect(detail.decisions).toHaveLength(1)
    expect(detail.decisions[0].reviewer).toBe('r@example.com')
    expect(detail.video_purge_on).not.toBeNull()
    const queue = await call<QueueResponse>('/api/review/queue')
    expect(queue.items.find((i) => i.candidate_id === 'cand-007')?.decision).toBe('concern_noted')
    const audit = await call<{ entries: { action: string; candidate_id: string | null }[] }>(
      '/api/review/audit',
    )
    expect(audit.entries[0]).toMatchObject({ action: 'decision', candidate_id: 'cand-007' })
  })

  it('gives each queue item a strength, a band and a flag count that agree', async () => {
    const queue = await call<QueueResponse>('/api/review/queue')
    for (const item of queue.items) {
      expect(item.strength).toBeGreaterThanOrEqual(1)
      expect(item.strength).toBeLessThanOrEqual(5)
      expect(item.band).toBe(item.strength >= 4 ? 'high' : item.strength === 3 ? 'moderate' : 'low')
      expect(item.flag_count).toBe(item.flag_kinds.length)
    }
    expect(queue.items.find((i) => i.logging_only)?.band).toBe('low')
    const detail = await call<CandidateDetail>('/api/review/candidates/cand-007')
    expect([detail.strength, detail.band]).toEqual([5, 'high'])
  })

  it('builds the overview from the queue and moves a candidate to reviewed on a decision', async () => {
    const before = await call<OverviewResponse>('/api/review/overview')
    expect(before.tiles.flagged).toBe(7)
    expect(before.tiles.reviewed).toBe(1) // cand-018 arrives decided
    expect(before.pending).toBe(6)
    expect(before.next_up.map((n) => n.candidate_id)).toEqual(['cand-007', 'cand-012', 'cand-003'])
    const counts = before.flags_by_kind.map((k) => k.count)
    expect(counts).toEqual([...counts].sort((a, b) => b - a))
    expect(before.checks.map((c) => c.key)).toContain('heartbeat')

    await call('/api/review/decisions', 'POST', {
      session_id: 'sess-cand-007',
      outcome: 'no_concern',
      reason: 'Nothing on the video supports the flags raised here.',
    })
    const after = await call<OverviewResponse>('/api/review/overview')
    expect(after.pending).toBe(5)
    expect(after.next_up[0].candidate_id).toBe('cand-012')
  })

  it('has an empty overview for a sitting that has not run', async () => {
    const overview = await call<OverviewResponse>('/api/review/overview?sitting=2')
    expect(overview.tiles.flagged).toBe(0)
    expect(overview.next_up).toEqual([])
    expect(overview.sitting_status).toBe('closed')
  })

  it('toggles the shortlist', async () => {
    const first = await call<{ shortlisted: boolean }>(
      '/api/review/candidates/cand-012/shortlist',
      'POST',
    )
    const second = await call<{ shortlisted: boolean }>(
      '/api/review/candidates/cand-012/shortlist',
      'POST',
    )
    expect([first.shortlisted, second.shortlisted]).toEqual([true, false])
  })

  it('answers 404 for a candidate that is not in the queue', async () => {
    expect(await codeOf(call('/api/review/candidates/cand-999'))).toBe('candidate_not_found')
  })
})

describe('mock admin', () => {
  const admin = <T>(path: string, method = 'GET', body?: unknown) => call<T>(path, method, body, ADMIN)

  it('refuses to close a sitting with unfinished candidates unless forced', async () => {
    expect(await codeOf(admin('/api/admin/sittings/1/close', 'POST', { force: false }))).toBe(
      'sessions_unfinished',
    )
    await expect(admin('/api/admin/sittings/1/close', 'POST', { force: true })).resolves.toEqual({
      status: 'closed',
      forced: true,
    })
    const list = await admin<{ sittings: AdminSitting[] }>('/api/admin/sittings')
    expect(list.sittings.find((s) => s.id === 1)?.status).toBe('closed')
  })

  it('creates a sitting from a number per section and validates it', async () => {
    const body = {
      name: 'Pilot',
      opens_at: null,
      closes_at: null,
      duration_s: 1800,
      per_section: { numerical: 4, verbal: 3 },
    }
    expect(await codeOf(admin('/api/admin/sittings', 'POST', { ...body, name: ' ' }))).toBe(
      'name_required',
    )
    expect(
      await codeOf(admin('/api/admin/sittings', 'POST', { ...body, per_section: { numerical: 500 } })),
    ).toBe('section_too_small')
    expect(
      await codeOf(admin('/api/admin/sittings', 'POST', { ...body, per_section: { astrology: 2 } })),
    ).toBe('unknown_section')
    expect(await codeOf(admin('/api/admin/sittings', 'POST', { ...body, per_section: {} }))).toBe(
      'invalid_question_count',
    )
    const created = await admin<AdminSitting>('/api/admin/sittings', 'POST', body)
    expect(created).toMatchObject({
      name: 'Pilot',
      status: 'open',
      question_count: 7,
      blueprint: { numerical: 4, verbal: 3 },
    })
  })

  it('lists the invited candidates with where each one is, and makes a new code for one', async () => {
    const list = await admin<InviteListResponse>('/api/admin/invites')
    expect(list.total).toBe(20)
    expect(list.invites.map((i) => i.status)).toContain('not_opened')
    expect(list.invites[0]).not.toHaveProperty('code')

    const fresh = await admin<{ candidate_id: string; code: string }>(
      '/api/admin/invites/cand-016/reissue',
      'POST',
    )
    expect(fresh.candidate_id).toBe('cand-016')
    expect(fresh.code).toMatch(/^[0-9A-Z]{8}$/)
    expect(await codeOf(admin('/api/admin/invites/nobody/reissue', 'POST'))).toBe('candidate_not_found')
  })

  it('pages the questions and filters them by section', async () => {
    const first = await admin<QuestionListResponse>('/api/admin/questions?limit=25')
    expect(first.total).toBe(60)
    expect(first.questions).toHaveLength(25)
    const verbal = await admin<QuestionListResponse>('/api/admin/questions?section=verbal&limit=500')
    expect(verbal.total).toBe(20)
    expect(new Set(verbal.questions.map((q) => q.section))).toEqual(new Set(['verbal']))
    expect(verbal.questions[0].pct_correct).toBeNull() // made-up questions have no real figure
  })

  it('generates short codes with new candidate IDs and no repeats', async () => {
    const result = await admin<InvitesResponse>('/api/admin/invites', 'POST', { count: 50 })
    expect(result.invites).toHaveLength(50)
    for (const invite of result.invites) expect(invite.code).toMatch(/^[0-9A-HJKMNP-TV-Z]{8}$/)
    expect(new Set(result.invites.map((i) => i.candidate_id)).size).toBe(50)
    expect(result.invites[0].candidate_id).toBe('cand-021')
    expect(await codeOf(admin('/api/admin/invites', 'POST', { count: 0 }))).toBe('invalid_count')
  })

  it('will not touch the question bank while a sitting is open', async () => {
    expect(
      await codeOf(
        admin('/api/admin/questions/import', 'POST', { filename: 'a.csv', summary_csv: 'x' }),
      ),
    ).toBe('sitting_open')
    expect(await codeOf(admin('/api/admin/questions/retire-synthetic', 'POST', {}))).toBe(
      'sitting_open',
    )
  })

  it('imports a summary, reports rejects, and counts questions by source', async () => {
    await admin('/api/admin/sittings/1/close', 'POST', { force: true })
    const header = 'question_id,section,correct_option,difficulty_tag,n_candidates,pct_correct,median_s,p25_s,p75_s'
    const csv = [
      header,
      'C001,Numerical,A,easy,400,62,30,20,45', // percentage as 62 is accepted
      'C002,Numerical,B,,400,0.4,50,40,70', // no tag: derived
      'C003,Verbal,C,hard,400,0.2,60,70,90', // p25 above the median
      'C001,Verbal,D,easy,400,0.9,20,10,30', // duplicate id
    ].join('\n')
    const report = await admin<ImportReport>('/api/admin/questions/import', 'POST', {
      filename: 'summary.csv',
      summary_csv: csv,
      bank_csv: null,
    })
    expect(report.imported).toBe(2)
    expect(report.rows).toBe(4)
    expect(report.rejected.map((r) => r.reason)).toEqual([
      'p25 <= median <= p75 does not hold',
      'duplicate question_id',
    ])
    expect(report.difficulty_derived).toBe(1)
    expect(report.warnings.some((w) => w.includes('no question text'))).toBe(true)

    const summary = await admin<{ cytonn: number; synthetic: number }>(
      '/api/admin/questions/summary',
    )
    expect(summary).toMatchObject({ cytonn: 2, synthetic: 60 })
  })

  it('rejects a summary with missing columns', async () => {
    await admin('/api/admin/sittings/1/close', 'POST', { force: true })
    const error = await admin('/api/admin/questions/import', 'POST', {
      filename: 'bad.csv',
      summary_csv: 'question_id,section\nQ1,verbal',
    }).catch((e: unknown) => e)
    expect(error).toBeInstanceOf(ApiError)
    expect((error as ApiError).code).toBe('missing_columns')
    expect(Array.isArray((error as ApiError).body.columns)).toBe(true)
  })

  it('removes the placeholders once no sitting is open', async () => {
    await admin('/api/admin/sittings/1/close', 'POST', { force: true })
    await expect(
      admin('/api/admin/questions/retire-synthetic', 'POST', {}),
    ).resolves.toEqual({ removed: 60, kept: 0 })
    const summary = await admin<{ total: number }>('/api/admin/questions/summary')
    expect(summary.total).toBe(0)
  })
})

describe('mock candidate endpoints', () => {
  const candidate = <T>(path: string, method = 'GET', body?: unknown) =>
    call<T>(path, method, body, 'candidate-token')

  it('passes the pre-check only when camera and microphone both worked', async () => {
    const ok = { camera_ok: true, mic_ok: true }
    await expect(candidate('/api/precheck/result', 'POST', ok)).resolves.toEqual({ passed: true })
    await expect(
      candidate('/api/precheck/result', 'POST', { ...ok, mic_ok: false }),
    ).resolves.toEqual({ passed: false })
  })

  it('waives the microphone only when its step was left out, never when it failed', async () => {
    const send = (body: object) => candidate('/api/precheck/result', 'POST', body)
    await expect(send({ camera_ok: true, mic_ok: false, mic_checked: false })).resolves.toEqual({
      passed: true,
    })
    await expect(send({ camera_ok: true, mic_ok: false, mic_checked: true })).resolves.toEqual({
      passed: false,
    })
    await expect(send({ camera_ok: false, mic_ok: false, mic_checked: false })).resolves.toEqual({
      passed: false,
    })
  })

  it('validates complaints', async () => {
    expect(await codeOf(candidate('/api/complaints', 'POST', { category: 'x', text: 'a' }))).toBe(
      'invalid_complaint',
    )
    expect(
      await codeOf(candidate('/api/complaints', 'POST', { category: 'camera', text: ' ' })),
    ).toBe('invalid_complaint')
    expect(
      await codeOf(
        candidate('/api/complaints', 'POST', { category: 'other', text: 'x'.repeat(1001) }),
      ),
    ).toBe('invalid_complaint')
    await expect(
      candidate('/api/complaints', 'POST', { category: 'upload', text: 'It stopped at 40%.' }),
    ).resolves.toBeUndefined()
  })

  it('moves the upload manifest forward on each poll until it is complete', async () => {
    const seen: number[] = []
    let complete = false
    for (let i = 0; i < 10 && !complete; i++) {
      const m = await candidate<{ received: number; complete: boolean; missing: number }>(
        '/api/chunks/s1/manifest',
      )
      seen.push(m.received)
      complete = m.complete
      expect(m.received + m.missing).toBe(42)
    }
    expect(complete).toBe(true)
    expect(seen).toEqual([...seen].sort((a, b) => a - b))
  })
})
