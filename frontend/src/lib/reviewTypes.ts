// Response shapes for /api/review/* (master plan section 7.2, D13). Candidate IDs only, never
// names. Seek maths is the server's job (services/video/seek.py): the page uses what it is given.

export type AiStatus = 'ok' | 'retried' | 'fallback' | 'not_run'

export type DecisionOutcome = 'no_concern' | 'concern_noted' | 'refer_for_follow_up'

/** How soon a person might want to look. A label for the queue: it sets no one aside. */
export type Band = 'high' | 'moderate' | 'low'

/** Every decision needs a written reason of at least this many characters (D13). */
export const MIN_REASON_CHARS = 20

export interface SittingRef {
  id: number
  name: string
}

export interface QueueItem {
  candidate_id: string
  rank: number
  rule_score: number
  ai_strength: number | null // 1 to 5, null when the order is rules only
  ai_status: AiStatus
  strength: number // 1 to 5: the AI's when it answered, else the rules'
  band: Band
  flag_count: number
  flag_kinds: string[]
  decision: DecisionOutcome | null
  shortlisted: boolean
  logging_only: boolean // only a logging problem: sits in its own low lane
}

export interface QueueResponse {
  sittings: SittingRef[]
  sitting_id: number
  items: QueueItem[]
}

/** Where a moment sits in the saved video, or null when nothing was recorded at that moment. */
export interface VideoSeek {
  segment: number
  seek_s: number // already 5 s before the moment
}

export interface FlagItem {
  id: string
  kind: string
  server_ts: string
  elapsed_s: number
  question_number: number | null
  detail: Record<string, unknown>
  video_seek: VideoSeek | null
}

export interface MicSilence {
  id: string
  start_s: number
  end_s: number
  duration_s: number
  layers: ('browser' | 'server')[]
  video_seek: VideoSeek | null
}

export interface InnocentSignal {
  id: string
  kind: string
  elapsed_s?: number
  duration_s?: number
  category?: string
  note?: string
}

export interface VsSitting {
  cohort_skipped?: 'too_small'
  pace_percentile?: number
  spread_percentile?: number
  score_percentile?: number
}

export interface Explanation {
  source: 'ai' | 'rules'
  status: AiStatus
  text: string
  strength: number | null
  flags_support_each_other: 'yes' | 'partly' | 'no' | null
}

export interface ComplaintItem {
  id: string
  category: 'camera' | 'upload' | 'other'
  text: string
  created_at: string
  status: 'open' | 'reviewed'
}

export interface PastDecision {
  outcome: DecisionOutcome
  reason: string
  reviewer: string
  decided_at: string
}

export interface VideoSegment {
  segment: number
  url: string | null // short-lived, served with Range support; null when not available
  start_s: number // offset from the recording anchor
  duration_s: number
}

export interface BreakdownLine {
  label: string
  points: number
}

export interface CandidateDetail {
  session_id: string
  candidate_id: string
  rank: number
  strength: number
  band: Band
  rule_score: number
  rule_breakdown: BreakdownLine[]
  score: number
  pace_s_per_q: number
  history_source: 'cytonn' | 'synthetic' | 'none'
  flags: FlagItem[]
  vs_sitting: VsSitting
  innocent_signals: InnocentSignal[]
  mic_silence: MicSilence[]
  self_report: { had_technical_issues: boolean; note: string | null } | null
  explanation: Explanation
  complaints: ComplaintItem[]
  decisions: PastDecision[]
  shortlisted: boolean
  segments: VideoSegment[]
  video_deleted_at: string | null
  video_purge_on: string | null
}

export interface DecisionRequest {
  session_id: string
  outcome: DecisionOutcome
  reason: string
}

export interface AuditEntry {
  id: string
  ts: string
  reviewer: string
  action: 'login' | 'decision' | 'video_view' | 'video_purged' | 'admin'
  candidate_id: string | null
  detail: string
}

export interface LoginResponse {
  token: string
  email: string
  role: 'reviewer' | 'admin'
}

export interface OverviewTiles {
  sat: number
  finished: number
  flagged: number
  reviewed: number
  videos_uploaded: number
  videos_expected: number
  videos_decided_not_deleted: number
}

export interface HealthCheck {
  key: string
  label: string
  state: 'ok' | 'warn' | 'off' | 'note'
  detail: string
}

export interface NextUp {
  candidate_id: string
  band: Band
  flag_count: number
  first_kind: string
}

export interface OverviewResponse {
  sittings: SittingRef[]
  sitting_id: number
  sitting_status: 'open' | 'closed' | null
  tiles: OverviewTiles
  flags_by_kind: { kind: string; count: number }[]
  pending: number // queue candidates still without a decision
  next_up: NextUp[]
  checks: HealthCheck[]
}
