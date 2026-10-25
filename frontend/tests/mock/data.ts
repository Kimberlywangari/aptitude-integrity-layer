// Fixtures for the screens whose backend is not built yet. Shapes follow master plan 7.2 and
// 7.5; the people are the same kinds of case as eval/fixtures/synthetic_packets.py. Candidate IDs
// only, never names.

import type {
  ActionLog,
  AiStatus,
  AuditEntry,
  Band,
  BreakdownLine,
  CandidateDetail,
  CandidateRow,
  ComplaintItem,
  FlagItem,
  HealthCheck,
  InnocentSignal,
  MicSilence,
  NextUp,
  OverviewTiles,
  PastDecision,
  QueueItem,
  SittingRef,
  VideoSegment,
  VideoSeek,
  VsSitting,
} from '../../src/lib/reviewTypes'

export const SITTINGS: SittingRef[] = [
  { id: 1, name: 'Synthetic sitting 1' },
  { id: 2, name: 'Pilot sitting 28 Oct (not run yet)' },
]

const BASE_MS = Date.UTC(2026, 9, 28, 9, 0, 0)

export function isoAt(elapsedS: number): string {
  return new Date(BASE_MS + elapsedS * 1000).toISOString()
}

interface Template {
  weight: number
  question: number | null
  detail: Record<string, unknown>
}

// Weights are the proposed defaults in master plan 7.4.
const TEMPLATES: Record<string, Template> = {
  COPY_ATTEMPT: { weight: 3, question: 9, detail: { target: 'question_text', length: 212 } },
  LONG_HOLD_CORRECT: {
    weight: 4,
    question: 22,
    detail: { time_s: 212, own_median_s: 38, focus_lost_s: 44 },
  },
  CORRECT_RUN_AFTER_GAP: {
    weight: 2,
    question: 23,
    detail: { gap_s: 74, run_length: 3, mean_s: 6.2, own_median_s: 38 },
  },
  FOCUS_LOSS: { weight: 0.5, question: 5, detail: { focus_lost_s: 44 } },
  PACE_OUTLIER: { weight: 1.5, question: null, detail: { direction: 'fast', robust_z: -3.2 } },
  SPREAD_OUTLIER: { weight: 1.5, question: null, detail: { direction: 'narrow', robust_z: -3.8 } },
  LOGGING_PROBLEM: { weight: 0, question: null, detail: { heartbeat_gap_s: 52 } },
}

interface Seed {
  id: string
  kinds: string[]
  at: number[] // elapsed seconds, one per kind
  ai: { status: AiStatus; strength: number | null; text: string }
  score: number
  pace: number
  vs: VsSitting
  innocent?: InnocentSignal[]
  mic?: Omit<MicSilence, 'video_seek'>[]
  selfReport?: { had_technical_issues: boolean; note: string | null }
  complaints?: ComplaintItem[]
  decisions?: PastDecision[]
  shortlisted?: boolean
  segments?: { start_s: number; duration_s: number }[]
  videoDeletedAt?: string
}

const WHOLE_TEST = [{ start_s: 0, duration_s: 1900 }]
const COHORT = { pace_percentile: 8, spread_percentile: 3, score_percentile: 91 }

// Order in this list is the queue's rank order.
const SEEDS: Seed[] = [
  {
    id: 'cand-007',
    kinds: ['COPY_ATTEMPT', 'LONG_HOLD_CORRECT', 'CORRECT_RUN_AFTER_GAP'],
    at: [310, 1125, 1410],
    ai: {
      status: 'ok',
      strength: 5,
      text:
        'Three different kinds of flag appear within about 20 minutes. A copy attempt on question 9 ' +
        'copied 212 characters. On question 22 the candidate took 212 s against their own median of ' +
        '38 s and answered correctly after losing focus for 44 s. Three correct answers in a row, ' +
        'averaging 6 s each, followed a 74 s gap. The innocent signals do not explain any of these.',
    },
    score: 34,
    pace: 21,
    vs: COHORT,
    mic: [
      { id: 'M1', start_s: 1180, end_s: 1255, duration_s: 75, layers: ['browser', 'server'] },
    ],
    segments: WHOLE_TEST,
  },
  {
    id: 'cand-012',
    kinds: ['COPY_ATTEMPT', 'FOCUS_LOSS', 'LONG_HOLD_CORRECT', 'CORRECT_RUN_AFTER_GAP'],
    at: [140, 158, 700, 905],
    ai: {
      status: 'ok',
      strength: 4,
      text:
        'A copy attempt on question 4 is followed 18 s later by a 44 s loss of focus on question 5, ' +
        'which was answered correctly. Question 12 took 180 s against a median of 30 s. Four correct ' +
        'answers in a row came after an 88 s gap. A 9 s connection drop at 400 s sits away from ' +
        'these moments.',
    },
    score: 29,
    pace: 19,
    vs: { pace_percentile: 12, spread_percentile: 20, score_percentile: 84 },
    innocent: [{ id: 'I1', kind: 'connection_lost', elapsed_s: 400, duration_s: 9 }],
    segments: WHOLE_TEST,
  },
  {
    id: 'cand-003',
    kinds: ['CORRECT_RUN_AFTER_GAP', 'SPREAD_OUTLIER', 'PACE_OUTLIER'],
    at: [1210, 1900, 1900],
    ai: {
      status: 'retried',
      strength: 4,
      text:
        'Three correct answers in a row, 4 to 6 s each against a median of 31 s, followed a gap. ' +
        'The answer-time spread and the pace are both far from the sitting. The two cohort flags ' +
        'describe the same pattern as the quick run.',
    },
    score: 31,
    pace: 14,
    vs: { pace_percentile: 2, spread_percentile: 1, score_percentile: 88 },
    segments: WHOLE_TEST,
  },
  {
    id: 'cand-015',
    kinds: ['COPY_ATTEMPT', 'FOCUS_LOSS', 'CORRECT_RUN_AFTER_GAP'],
    at: [520, 1700, 930],
    ai: {
      status: 'fallback',
      strength: null,
      text:
        'The AI check did not pass the fact check, so this candidate keeps the order the rules ' +
        'gave: one copy attempt (140 characters), one loss of focus and a run of correct answers ' +
        'after a gap. The camera dropped between 900 s and 960 s, so the third flag has no video.',
    },
    score: 22,
    pace: 38,
    vs: { pace_percentile: 48, spread_percentile: 55, score_percentile: 52 },
    innocent: [
      { id: 'I1', kind: 'camera_dropped', elapsed_s: 900, duration_s: 60 },
      { id: 'I2', kind: 'connection_lost', elapsed_s: 905, duration_s: 40 },
    ],
    // a gap between two recorder segments: flags inside it have no video
    segments: [
      { start_s: 0, duration_s: 900 },
      { start_s: 960, duration_s: 940 },
    ],
    complaints: [
      {
        id: 'K1',
        category: 'camera',
        text: 'My camera light went off for about a minute in the middle of the test.',
        created_at: isoAt(2100),
        status: 'open',
      },
    ],
  },
  {
    id: 'cand-009',
    kinds: ['LONG_HOLD_CORRECT', 'CORRECT_RUN_AFTER_GAP'],
    at: [400, 900],
    ai: {
      status: 'ok',
      strength: 2,
      text:
        'Question 8 took 130 s against a median of 40 s, and three correct answers followed a 61 s ' +
        'gap. The candidate reported a screen freeze, which may account for the gap. The two flags ' +
        'are 500 s apart.',
    },
    score: 25,
    pace: 33,
    vs: { pace_percentile: 50, spread_percentile: 47, score_percentile: 64 },
    innocent: [
      { id: 'I1', kind: 'self_report', category: 'technical_issue', note: 'screen froze once' },
    ],
    selfReport: { had_technical_issues: true, note: 'The screen froze once for about a minute.' },
    segments: WHOLE_TEST,
  },
  {
    id: 'cand-018',
    kinds: ['PACE_OUTLIER'],
    at: [1900],
    ai: {
      status: 'not_run',
      strength: null,
      text: 'Rules only: a single cohort flag. Mean time per question is far faster than the sitting.',
    },
    score: 38,
    pace: 17,
    vs: { pace_percentile: 5, spread_percentile: 40, score_percentile: 96 },
    shortlisted: true,
    decisions: [
      {
        outcome: 'no_concern',
        reason: 'Only a pace flag, no other evidence; pace is steady on the video review.',
        reviewer: 'reviewer@example.com',
        decided_at: '2026-09-02T10:30:00Z',
      },
    ],
    segments: WHOLE_TEST,
    videoDeletedAt: '2026-10-02T10:30:00Z',
  },
  {
    id: 'cand-004',
    kinds: ['LOGGING_PROBLEM'],
    at: [1500],
    ai: {
      status: 'not_run',
      strength: null,
      text: 'Rules only: no heartbeat for 52 s that a dropped connection or reload does not explain.',
    },
    score: 20,
    pace: 41,
    vs: { cohort_skipped: 'too_small' },
    segments: WHOLE_TEST,
  },
]

// ---- builders

// The same cut points as backend/app/services/ranking/rules.py: a rule score as a 1 to 5 strength.
const STRENGTH_CUTS = [2, 4, 6, 9]

export function bandOf(strength: number): Band {
  if (strength >= 4) return 'high'
  return strength === 3 ? 'moderate' : 'low'
}

function strengthOf(seed: Seed, ruleScore: number): number {
  if (seed.ai.strength !== null) return seed.ai.strength
  if (seed.kinds.every((k) => k === 'LOGGING_PROBLEM')) return 1
  return 1 + STRENGTH_CUTS.filter((cut) => ruleScore >= cut).length
}

export function seekFor(
  segments: { start_s: number; duration_s: number }[],
  elapsedS: number,
): VideoSeek | null {
  const index = segments.findIndex(
    (s) => elapsedS >= s.start_s && elapsedS <= s.start_s + s.duration_s,
  )
  if (index < 0) return null
  return { segment: index, seek_s: Math.max(0, elapsedS - segments[index].start_s - 5) }
}

function breakdown(flags: FlagItem[]): BreakdownLine[] {
  const lines: BreakdownLine[] = flags.map((f) => ({
    label: `${f.kind} (${f.id})`,
    points: TEMPLATES[f.kind]?.weight ?? 0,
  }))
  const kinds = new Set(flags.map((f) => f.kind))
  if (kinds.size > 1) lines.push({ label: 'Extra distinct kinds (+1 each)', points: kinds.size - 1 })
  const times = flags.map((f) => f.elapsed_s).sort((a, b) => a - b)
  if (times.some((t, i) => i > 0 && t - times[i - 1] <= 120)) {
    lines.push({ label: 'Two flags within 120 s', points: 1 })
  }
  return lines
}

export interface MockState {
  decisions: Map<string, PastDecision[]>
  shortlisted: Set<string>
  audit: AuditEntry[]
}

export function initialState(): MockState {
  const decisions = new Map<string, PastDecision[]>()
  const shortlisted = new Set<string>()
  for (const seed of SEEDS) {
    if (seed.decisions) decisions.set(seed.id, [...seed.decisions])
    if (seed.shortlisted) shortlisted.add(seed.id)
  }
  const audit: AuditEntry[] = [
    {
      id: 'A1',
      ts: '2026-09-02T10:28:00Z',
      reviewer: 'reviewer@example.com',
      action: 'login',
      candidate_id: null,
      detail: 'signed in',
    },
    {
      id: 'A2',
      ts: '2026-09-02T10:30:00Z',
      reviewer: 'reviewer@example.com',
      action: 'decision',
      candidate_id: 'cand-018',
      detail: 'no_concern',
    },
    {
      id: 'A3',
      ts: '2026-10-02T10:30:00Z',
      reviewer: 'system',
      action: 'video_purged',
      candidate_id: 'cand-018',
      detail: '30 days after the decision',
    },
  ]
  return { decisions, shortlisted, audit }
}

// People the queue leaves out: nothing to flag, or still sitting. They show in "Everyone".
interface Quiet {
  id: string
  status: CandidateRow['status']
  resolved: number
  score: number
  pace: number
}

const QUIET: Quiet[] = [
  { id: 'cand-001', status: 'finished', resolved: 12, score: 18, pace: 36 },
  { id: 'cand-020', status: 'in_progress', resolved: 7, score: 0, pace: 0 },
  { id: 'cand-021', status: 'created', resolved: 0, score: 0, pace: 0 },
]

function quietDetail(id: string, state: MockState): CandidateDetail | null {
  const quiet = QUIET.find((q) => q.id === id)
  if (!quiet) return null
  const shortlisted = state.shortlisted.has(id)
  return {
    session_id: `sess-${id}`,
    candidate_id: id,
    rank: 0,
    strength: 1,
    band: 'low',
    rule_score: 0,
    rule_breakdown: [],
    score: quiet.score,
    pace_s_per_q: quiet.pace,
    flags: [],
    vs_sitting: { cohort_skipped: 'too_small' },
    innocent_signals: [],
    mic_silence: [],
    self_report: null,
    explanation: {
      source: 'rules',
      status: 'not_run',
      text: 'Rules only: no flags in the record.',
      strength: null,
      flags_support_each_other: null,
    },
    complaints: [],
    decisions: state.decisions.get(id) ?? [],
    shortlisted,
    video_available: shortlisted,
    segments: [],
    video_deleted_at: null,
    video_purge_on: null,
  }
}

export function buildDetail(id: string, state: MockState): CandidateDetail | null {
  const index = SEEDS.findIndex((s) => s.id === id)
  if (index < 0) return quietDetail(id, state)
  const seed = SEEDS[index]
  const segs = seed.segments ?? WHOLE_TEST

  const flags: FlagItem[] = seed.kinds.map((kind, i) => ({
    id: `F${i + 1}`,
    kind,
    server_ts: isoAt(seed.at[i]),
    elapsed_s: seed.at[i],
    question_number: TEMPLATES[kind].question,
    detail: TEMPLATES[kind].detail,
    video_seek: seekFor(segs, seed.at[i]),
  }))
  const lines = breakdown(flags)
  const ruleScore = lines.reduce((sum, l) => sum + l.points, 0)
  const decisions = state.decisions.get(id) ?? []
  const latest = decisions[decisions.length - 1]
  const purgeOn = latest
    ? new Date(new Date(latest.decided_at).getTime() + 30 * 86_400_000).toISOString()
    : null

  const videoSegments: VideoSegment[] = segs.map((s, i) => ({
    segment: i,
    url: null, // no real video in mock mode
    start_s: s.start_s,
    duration_s: s.duration_s,
  }))

  const strength = strengthOf(seed, ruleScore)
  return {
    session_id: `sess-${id}`,
    candidate_id: id,
    rank: index + 1,
    strength,
    band: bandOf(strength),
    rule_score: ruleScore,
    rule_breakdown: lines,
    score: seed.score,
    pace_s_per_q: seed.pace,
    flags,
    vs_sitting: seed.vs,
    innocent_signals: seed.innocent ?? [],
    mic_silence: (seed.mic ?? []).map((m) => ({ ...m, video_seek: seekFor(segs, m.start_s) })),
    self_report: seed.selfReport ?? null,
    explanation: {
      source: seed.ai.status === 'ok' || seed.ai.status === 'retried' ? 'ai' : 'rules',
      status: seed.ai.status,
      text: seed.ai.text,
      strength: seed.ai.strength,
      flags_support_each_other: seed.ai.strength === null ? null : seed.ai.strength >= 4 ? 'yes' : 'partly',
    },
    complaints: seed.complaints ?? [],
    decisions,
    shortlisted: state.shortlisted.has(id),
    video_available: true,
    segments: videoSegments,
    video_deleted_at: seed.videoDeletedAt ?? null,
    video_purge_on: purgeOn,
  }
}

export function buildQueue(sittingId: number, state: MockState): QueueItem[] {
  if (sittingId !== 1) return []
  return SEEDS.map((seed, i): QueueItem => {
    const detail = buildDetail(seed.id, state) as CandidateDetail
    const decisions = state.decisions.get(seed.id) ?? []
    return {
      candidate_id: seed.id,
      rank: i + 1,
      rule_score: detail.rule_score,
      ai_strength: seed.ai.strength,
      ai_status: seed.ai.status,
      strength: detail.strength,
      band: detail.band,
      flag_count: seed.kinds.length,
      flag_kinds: seed.kinds,
      decision: decisions.length ? decisions[decisions.length - 1].outcome : null,
      shortlisted: state.shortlisted.has(seed.id),
      logging_only: seed.kinds.every((k) => k === 'LOGGING_PROBLEM'),
    }
  })
}

/** Everyone in the sitting: the queue's candidates and the quiet ones, in invitation order. */
export function buildCandidates(sittingId: number, state: MockState): CandidateRow[] {
  if (sittingId !== 1) return []
  const row = (id: string, partial: Partial<CandidateRow>): CandidateRow => {
    const decisions = state.decisions.get(id) ?? []
    return {
      candidate_id: id,
      status: 'finished',
      resolved: 12,
      total: 12,
      flag_count: 0,
      flag_kinds: [],
      in_queue: false,
      decision: decisions.length ? decisions[decisions.length - 1].outcome : null,
      shortlisted: state.shortlisted.has(id),
      ...partial,
    }
  }
  const flagged = SEEDS.map((seed) =>
    row(seed.id, {
      flag_count: seed.kinds.length,
      flag_kinds: [...new Set(seed.kinds)],
      in_queue: true,
    }),
  )
  const quiet = QUIET.map((q) => row(q.id, { status: q.status, resolved: q.resolved }))
  return [...flagged, ...quiet].sort(
    (a, b) =>
      a.candidate_id.length - b.candidate_id.length ||
      a.candidate_id.localeCompare(b.candidate_id),
  )
}

/** A made-up record for any candidate the mock knows: the shape the server sends, a few lines long. */
export function buildActionLog(id: string, state: MockState): ActionLog | null {
  const detail = buildDetail(id, state)
  if (!detail) return null
  const quiet = QUIET.find((q) => q.id === id)
  const status = quiet?.status ?? 'finished'
  const sat = status !== 'created'
  const event = (
    type: string,
    at_s: number,
    question: number | null,
    extra: Record<string, unknown> = {},
  ) => ({ type, at_s, question, detail: extra })
  return {
    candidate_id: id,
    status,
    started_at: sat ? isoAt(0) : null,
    finished_at: status === 'finished' ? isoAt(1800) : null,
    total_events: sat ? 8 : 0,
    truncated: false,
    heartbeats: sat ? 24 : 0,
    events: sat
      ? [
          event('page_load', -12, null),
          event('device_info', -10, null, { camera_label: 'Integrated Webcam', mic_label: 'Microphone Array' }),
          event('question_opened', 0, 1),
          event('focus_lost', 14, 1),
          event('focus_returned', 21, 1),
          event('answered', 30, 1),
          event('question_opened', 30, 2),
          event('copy_attempt', 41, 2, { length: 212 }),
        ]
      : [],
    questions: sat
      ? [
          { position: 1, section: 'numerical', difficulty: 'easy', opened_s: 0, answered_s: 30, time_s: 30, result: 'correct' },
          { position: 2, section: 'verbal', difficulty: 'hard', opened_s: 30, answered_s: 58.4, time_s: 28.4, result: 'wrong' },
          { position: 3, section: 'logical', difficulty: 'medium', opened_s: 58.4, answered_s: null, time_s: null, result: 'unanswered', written_by: 'ollama:qwen2.5:7b' },
        ]
      : [],
  }
}

// ---- the overview page

const CHECKS: HealthCheck[] = [
  {
    key: 'ai',
    label: 'AI ranking',
    state: 'off',
    detail: 'Rules only: the order comes from the rule score.',
  },
  {
    key: 'factcheck',
    label: 'Fact check on AI answers',
    state: 'ok',
    detail: 'Every AI answer is checked against the stored log before a reviewer sees it.',
  },
  {
    key: 'fallback',
    label: 'Rule order fallback',
    state: 'ok',
    detail: 'If the AI fails, the rule order is used.',
  },
  {
    key: 'gate',
    label: 'Camera and microphone gate',
    state: 'warn',
    detail: 'The test starts without the camera and microphone check. Fine for development.',
  },
]

export function buildOverview(
  sittingId: number,
  state: MockState,
): {
  tiles: OverviewTiles
  flags_by_kind: { kind: string; count: number }[]
  pending: number
  next_up: NextUp[]
  checks: HealthCheck[]
} {
  const queue = buildQueue(sittingId, state)
  const waiting = queue.filter((item) => item.decision === null)
  const counts = new Map<string, number>()
  for (const item of queue) {
    for (const kind of item.flag_kinds) counts.set(kind, (counts.get(kind) ?? 0) + 1)
  }
  const gaps = counts.get('LOGGING_PROBLEM') ?? 0
  return {
    tiles: {
      sat: queue.length ? 16 : 0,
      finished: queue.length ? 14 : 0,
      flagged: queue.length,
      reviewed: queue.length - waiting.length,
      videos_uploaded: queue.length ? 13 : 0,
      videos_expected: queue.length ? 14 : 0,
      videos_decided_not_deleted: queue.filter((item) => item.decision !== null).length,
    },
    flags_by_kind: [...counts.entries()]
      .sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]))
      .map(([kind, count]) => ({ kind, count })),
    pending: waiting.length,
    next_up: waiting.slice(0, 3).map((item) => ({
      candidate_id: item.candidate_id,
      band: item.band,
      flag_count: item.flag_count,
      first_kind: item.flag_kinds[0],
    })),
    checks: [
      ...CHECKS,
      {
        key: 'heartbeat',
        label: 'Heartbeat gaps',
        state: gaps ? 'note' : 'ok',
        detail: gaps ? `${gaps} to look at.` : 'None in this sitting.',
      },
    ],
  }
}
