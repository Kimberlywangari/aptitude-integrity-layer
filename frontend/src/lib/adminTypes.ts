// Response shapes for /api/admin/* (the recruiter's setup screens). Thin wrappers over what the
// CLI jobs already do (seed, import_question_summary, close_sitting), so the page and the
// command line share one set of service functions on the server.

export interface SittingCounts {
  finished: number
  in_progress: number
  not_started: number
}

export interface AdminSitting {
  id: number
  name: string
  opens_at: string | null
  closes_at: string | null
  duration_s: number
  question_count: number
  blueprint: Record<string, number> | null // questions from each section; null = spread evenly
  status: 'open' | 'closed'
  counts: SittingCounts
}

export interface CreateSittingRequest {
  name: string
  opens_at: string | null
  closes_at: string | null
  duration_s: number
  /** How many questions each section contributes to a paper. */
  per_section: Record<string, number>
}

export interface CloseSittingResponse {
  status: 'closed'
  forced: boolean
}

export interface Invite {
  candidate_id: string
  code: string // shown once; the server keeps only a hash
}

export interface InvitesResponse {
  invites: Invite[]
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
}

export interface InviteListResponse {
  invites: InviteStatus[]
  total: number // all candidates; `invites` holds the newest
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
