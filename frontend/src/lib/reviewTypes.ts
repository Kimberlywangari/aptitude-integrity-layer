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

export type SessionStatus = 'created' | 'in_progress' | 'finished'

/** One line of the list of everyone in a sitting, flagged or not. */
export interface CandidateRow {
  candidate_id: string
  status: SessionStatus
  resolved: number // questions answered or skipped so far
  total: number
  flag_count: number
  flag_kinds: string[]
  in_queue: boolean // whether the queue shows them
  decision: DecisionOutcome | null
  shortlisted: boolean
}

export interface CandidatesResponse {
  sittings: SittingRef[]
  sitting_id: number
  items: CandidateRow[]
}

/** One thing the candidate's page reported, in server time. */
export interface LogEvent {
  type: string
  at_s: number | null // seconds from the start of the test; negative before the timer ran
  question: number | null // the question the candidate was on
  detail: Record<string, unknown>
}

export interface LogQuestion {
  position: number
  section: string
  difficulty: string | null
  opened_s: number | null
  answered_s: number | null
  time_s: number | null
  result: 'correct' | 'wrong' | 'skipped' | 'unanswered'
  /** Set when an AI wrote this question for this candidate, such as "ollama:qwen2.5:7b". */
  written_by?: string | null
}

export interface ActionLog {
  candidate_id: string
  status: SessionStatus
  started_at: string | null
  finished_at: string | null
  total_events: number
  truncated: boolean // more events were stored than are listed
  heartbeats: number
  events: LogEvent[]
  questions: LogQuestion[]
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
  flags: FlagItem[]
  vs_sitting: VsSitting
  innocent_signals: InnocentSignal[]
  mic_silence: MicSilence[]
  self_report: { had_technical_issues: boolean; note: string | null } | null
  explanation: Explanation
  complaints: ComplaintItem[]
  decisions: PastDecision[]
  shortlisted: boolean
  video_available: boolean // false: not flagged and not shortlisted, so the recording stays closed
  segments: VideoSegment[]
  video_deleted_at: string | null
  video_purge_on: string | null
  result: ResultPanel
}

export type EmailState = 'none' | 'queued' | 'sent' | 'failed'

/** The result emails: what a person decided, and whether it can be recorded now. No name, no address. */
export interface ResultPanel {
  score: number
  total: number
  pass_mark: number | null
  status: OutcomeStatus
  result: 'pass' | 'fail' | null
  basis: 'score' | 'review' | null
  reason: string | null
  decided_by: string | null
  decided_at: string | null
  email_state: EmailState
  can_record: boolean
  blocked_by: 'not_finished' | 'already_emailed' | 'no_email' | 'review_first' | null
  reasons: { key: string; text: string }[]
}

export interface ResultRequest {
  result: 'pass' | 'fail'
  reason_key?: string | null
  reason_text?: string | null
}

export type OutcomeStatus =
  | 'invited'
  | 'in_progress'
  | 'waiting_review'
  | 'in_review'
  | 'ready'
  | 'passed'
  | 'failed_score'
  | 'failed_review'
  | 'under_appeal'
  | 'incomplete'

export interface OutcomeItem {
  candidate_id: string
  status: OutcomeStatus
  score: number | null
  total: number | null
  flag_count: number
  email_state: EmailState
  has_email: boolean
  result_at: string | null
  can_mark_passed: boolean
  /** Only on the admin's copy of the list: the name, and the address with its middle hidden. */
  name?: string | null
  email?: string | null
}

export interface OutcomesResponse {
  sittings: SittingRef[]
  sitting_id: number
  pass_mark: number | null
  question_count: number
  sitting_closed: boolean
  counts: Record<OutcomeStatus, number>
  email_counts: Record<EmailState, number>
  total: number
  matching: number
  page: number
  page_size: number
  items: OutcomeItem[]
}

export interface BulkPassResponse {
  queued: number
  refused: { candidate_id: string; code: string }[]
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
