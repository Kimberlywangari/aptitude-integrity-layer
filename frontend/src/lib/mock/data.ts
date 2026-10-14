// Fixtures for the screens whose backend is not built yet. Shapes follow master plan 7.2 and
// 7.5; the people are the same kinds of case as eval/fixtures/synthetic_packets.py. Candidate IDs
// only, never names.

import type {
  AiStatus,
  AuditEntry,
  BreakdownLine,
  CandidateDetail,
  ComplaintItem,
  FlagItem,
  InnocentSignal,
  MicSilence,
  PastDecision,
  QueueItem,
  SittingRef,
  VideoSegment,
  VideoSeek,
  VsSitting,
} from '../reviewTypes'

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
    weight: 3,
    question: 22,
    detail: { time_s: 212, own_median_s: 38, focus_lost_during: true },
  },
  CORRECT_RUN_AFTER_GAP: { weight: 2, question: 23, detail: { gap_s: 74, run_length: 3 } },
  FAST_CORRECT_VS_HISTORY: {
    weight: 2,
    question: 30,
    detail: { questions: [30, 31], times_s: [7, 6], p25_s: [41, 38] },
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
  historySource?: 'cytonn' | 'synthetic'
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
    kinds: ['COPY_ATTEMPT', 'LONG_HOLD_CORRECT', 'CORRECT_RUN_AFTER_GAP', 'FAST_CORRECT_VS_HISTORY'],
    at: [310, 1125, 1410, 1852],
    ai: {
      status: 'ok',
      strength: 5,
      text:
        'Four different kinds of flag appear within about 26 minutes. A copy attempt on question 9 ' +
        'copied 212 characters. On question 22 the candidate took 212 s against their own median of ' +
        '38 s and answered correctly after losing focus. Three correct answers in a row followed a ' +
        '74 s gap. The innocent signals do not explain any of these.',
    },
    score: 34,
    pace: 21,
    vs: COHORT,
    historySource: 'cytonn',
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
    kinds: ['FAST_CORRECT_VS_HISTORY', 'CORRECT_RUN_AFTER_GAP', 'SPREAD_OUTLIER', 'PACE_OUTLIER'],
    at: [1000, 1210, 1900, 1900],
    ai: {
      status: 'retried',
      strength: 4,
      text:
        'Three hard questions were answered correctly in 4 to 6 s each, far under the 25th ' +
        'percentile for those questions. The answer-time spread and the pace are both far from the ' +
        'sitting. The two cohort flags describe the same pattern as the fast answers.',
    },
    score: 31,
    pace: 14,
    vs: { pace_percentile: 2, spread_percentile: 1, score_percentile: 88 },
    historySource: 'cytonn',
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

export function buildDetail(id: string, state: MockState): CandidateDetail | null {
  const index = SEEDS.findIndex((s) => s.id === id)
  if (index < 0) return null
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

  return {
    session_id: `sess-${id}`,
    candidate_id: id,
    rank: index + 1,
    rule_score: ruleScore,
    rule_breakdown: lines,
    score: seed.score,
    pace_s_per_q: seed.pace,
    history_source: seed.historySource ?? 'synthetic',
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
      flag_kinds: seed.kinds,
      decision: decisions.length ? decisions[decisions.length - 1].outcome : null,
      shortlisted: state.shortlisted.has(seed.id),
      logging_only: seed.kinds.every((k) => k === 'LOGGING_PROBLEM'),
    }
  })
}
