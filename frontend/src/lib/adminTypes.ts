// Response shapes for /api/admin/* (the recruiter's setup screens). Thin wrappers over what the
// CLI jobs already do (seed, import_question_summary, close_sitting), so the page and the
// command line share one set of service functions on the server.

/** Where a sitting's questions come from. `cytonn`: Cytonn's own. `ai`: written for each
 *  candidate. `practice`: the made-up bank, for trying things out. `bank`: any stored question
 *  (what every sitting was before there were modes; no screen offers it any more). */
export type QuestionMode = 'bank' | 'practice' | 'cytonn' | 'ai'

export interface SittingCounts {
  finished: number
  in_progress: number
  not_started: number
  /** AI sittings: candidates whose questions are still being written, or could not be. */
  papers_pending: number
  papers_failed: number
}

export interface AdminSitting {
  id: number
  name: string
  opens_at: string | null
  closes_at: string | null
  duration_s: number
  question_count: number
  blueprint: Record<string, number> | null // questions from each section; null = spread evenly
  question_mode: QuestionMode
  status: 'open' | 'closed'
  /** Correct answers needed to pass; empty means none is set. */
  pass_mark?: number | null
  counts: SittingCounts
}

export interface CreateSittingRequest {
  name: string
  opens_at: string | null
  closes_at: string | null
  /** How many questions each section (or, for an AI sitting, each category) contributes. */
  per_section: Record<string, number>
  question_mode: QuestionMode
}

export interface AiCategory {
  key: string
  label: string
  brief: string
}

/** Which model writes the questions and whether it looks reachable. */
export interface AiStatus {
  provider: 'ollama' | 'claude'
  model: string
  available: boolean
  detail: string
  max_per_category: number
  max_total: number
  categories: AiCategory[]
}

/** One question written for the "try the writer" panel. Never stored. */
export interface AiSample {
  category: string
  difficulty: string
  text: string
  options: string[]
  correct_index: number
  explanation: string
  written_by: string
  seconds: number
  rounds: number
  rejected: string[]
}

export interface RetryPapersResponse {
  restarted: number
}

export interface CloseSittingResponse {
  status: 'closed'
  forced: boolean
}

export interface Invite {
  candidate_id: string
  code: string // shown once; the server keeps only a hash
  /** Set when the invitation was made from a pasted list. */
  name?: string | null
  email?: string | null
}

export type MailState = 'queued' | 'sent' | 'failed'

export type ListProblemReason =
  | 'bad_email'
  | 'name_missing'
  | 'name_too_long'
  | 'repeated'
  | 'already_invited'

export interface ListProblem {
  line: number
  reason: ListProblemReason
  text: string
}

export interface PreviewList {
  people: { line: number; name: string; email: string }[]
  problems: ListProblem[]
  sitting_id: number
  sitting_name: string
}

export interface MailStatus {
  set_up: boolean
  from_address: string | null // masked
  queued: number
  sent: number
  failed: number
}

export interface EmailText {
  subject: string
  body: string
}

export interface ResultsPlan {
  sitting_closed: boolean
  pass_mark: number | null
  sent_passed: number
  sent_not_passed: number
  queued: number
  failed: number
  /** Finished, with no result recorded yet: a person (or the close, for a low score) must act. */
  held_back: string[]
  did_not_finish: number
  without_email: number
  preview_passed: EmailText
  preview_not_passed: EmailText
  preview_not_passed_review: EmailText
}

export interface PassMarkPreview {
  current: number | null
  value: number | null
  newly_below: number
  no_longer_below: number
  sitting_closed: boolean
  emails_now: number
}

export interface ProcessStep {
  label: string
  seconds: number
  note: string
}

/** Where "Process sitting" stands. `provider` and `model` are what a run started now would use. */
export interface ProcessStatus {
  state: 'idle' | 'running' | 'done' | 'failed'
  provider: 'rules' | 'ollama' | 'claude'
  model: string | null
  steps: ProcessStep[]
  error: string | null
  started_at: string | null
  finished_at: string | null
  last_ranked_at: string | null
}

export interface InvitesResponse {
  invites: Invite[]
  /** The sitting these codes open: every one of them starts that sitting's paper. */
  sitting_id: number
  sitting_name: string
}

export interface SectionSummary {
  section: string
  count: number
  cytonn: number
  synthetic: number
}

export interface QuestionBankSummary {
  total: number
  cytonn: number
  synthetic: number
  by_section: SectionSummary[]
}

export interface ImportRequest {
  filename: string
  summary_csv: string
  bank_csv: string | null
}

export interface RejectedRow {
  row: number
  question_id: string | null
  reason: string
}

export interface ImportReport {
  filename: string
  rows: number
  imported: number
  rejected: RejectedRow[]
  warnings: string[]
  difficulty_derived: number
}

export interface RetireResponse {
  removed: number
  kept: number // synthetic questions an earlier test session still points at
}

export type InviteState = 'not_opened' | 'opened' | 'started' | 'finished'

export interface InviteStatus {
  candidate_id: string
  status: InviteState
  /** Null for a code made before invitations belonged to a sitting. */
  sitting_id: number | null
  sitting_name: string | null
  name?: string | null
  email?: string | null // masked
  invite_mail?: MailState | null
}

export interface InviteListResponse {
  invites: InviteStatus[]
  total: number // all candidates; `invites` holds the newest
}

/** One person invited to a sitting, and where they are in it. */
export interface SittingCandidate {
  candidate_id: string
  state: InviteState
  /** Questions answered or skipped so far. */
  answered: number
  /** Null until the candidate has opened their link. */
  paper_status: 'pending' | 'ready' | 'failed' | null
  paper_error: string | null
  /** Seconds a pending paper has been waited for. */
  waited_s: number | null
  opened_at: string | null
  started_at: string | null
  finished_at: string | null
  name?: string | null
  email?: string | null // masked
  invite_mail?: MailState | null
  result_mail?: 'passed' | 'not_passed' | null
  result_mail_status?: MailState | null
}

export interface SittingDetail {
  sitting: AdminSitting
  candidates: SittingCandidate[]
}

export interface DeleteSittingResponse {
  sessions: number
  candidates: number
  questions: number
}

export interface QuestionRow {
  id: string
  section: string
  difficulty: 'easy' | 'medium' | 'hard' | null
  source: 'cytonn' | 'synthetic'
  preview: string
  pct_correct: number | null // Cytonn's figure as a percentage, null until a summary is loaded
  n: number | null
}

export interface QuestionListResponse {
  questions: QuestionRow[]
  total: number
}
