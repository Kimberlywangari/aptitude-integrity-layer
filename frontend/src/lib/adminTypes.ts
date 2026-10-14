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
  status: 'open' | 'closed'
  counts: SittingCounts
}

export interface CreateSittingRequest {
  name: string
  opens_at: string | null
  closes_at: string | null
  duration_s: number
  question_count: number
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
