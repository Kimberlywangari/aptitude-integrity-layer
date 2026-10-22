// Reviewer-facing wording. Placeholder until Cytonn confirms the outcomes and the labels
// (master plan R11). Nothing here may read as a verdict: the AI ranks and explains, a person
// decides.

import type { AiStatus, Band, DecisionOutcome } from '../lib/reviewTypes'

export const AI_LABEL =
  'AI-generated and advisory only. It ranks and explains; it is not a verdict and it decides nothing.'
export const RULES_LABEL = 'Rule-based summary. No AI was used for this candidate.'
export const CONTEXT_ONLY = 'Context only. Never a flag on its own.'
export const FACT_CHECKED =
  'Checked against the stored log before you see it: every flag, time and count it cites is in the evidence.'

/** The queue's priority bands. A label that says where to look first; nobody is set aside. */
export const BAND_LABELS: Record<Band, string> = {
  high: 'High',
  moderate: 'Moderate',
  low: 'Low',
}
export const BAND_NOTE =
  'Priority is a suggestion for where to start, worked out from the evidence. Every flagged ' +
  'candidate is in the queue, and nothing here is a verdict.'

export const OUTCOME_LABELS: Record<DecisionOutcome, string> = {
  no_concern: 'No concern',
  concern_noted: 'Concern noted',
  refer_for_follow_up: 'Refer for follow-up',
}

export const OUTCOMES_NOTE = 'Outcome wording is a placeholder until Cytonn confirms it.'

export const RETENTION_NOTE =
  'The newest decision counts. Video is deleted 30 days after it, and every decision and video ' +
  'view is written to the audit log.'

export const FLAG_LABELS: Record<string, string> = {
  FOCUS_LOSS: 'Focus lost',
  COPY_ATTEMPT: 'Copy or cut attempt',
  LONG_HOLD_CORRECT: 'Long hold, answered correctly',
  CORRECT_RUN_AFTER_GAP: 'Run of correct answers after a gap',
  PACE_OUTLIER: 'Pace far from the sitting',
  SPREAD_OUTLIER: 'Answer-time spread far from the sitting',
  FAST_CORRECT_VS_HISTORY: 'Correct far faster than past candidates',
  LOGGING_PROBLEM: 'Logging problem (heartbeat gap)',
}

export const DETAIL_LABELS: Record<string, string> = {
  target: 'where',
  length: 'length copied (characters)',
  time_s: 'time on the question (s)',
  own_median_s: "candidate's own median (s)",
  focus_lost_during: 'focus lost during it',
  gap_s: 'gap before the run (s)',
  run_length: 'correct in a row',
  questions: 'questions',
  times_s: 'times (s)',
  p25_s: 'past 25th percentile (s)',
  focus_lost_s: 'focus lost for (s)',
  robust_z: 'robust z',
  direction: 'direction',
  heartbeat_gap_s: 'no heartbeat for (s)',
}

export const INNOCENT_LABELS: Record<string, string> = {
  connection_lost: 'Connection lost',
  page_load: 'Page reloaded',
  camera_dropped: 'Camera dropped',
  self_report: 'Candidate report',
  upload_incomplete: 'Upload incomplete',
}

/** The text for the "what ordered this candidate" badge in the queue and the detail page. */
export function orderBasis(status: AiStatus, strength: number | null): string {
  if ((status === 'ok' || status === 'retried') && strength !== null) {
    return `AI advisory ${strength}/5${status === 'retried' ? ' (retried)' : ''}`
  }
  return status === 'fallback' ? 'Rules only (AI check failed)' : 'Rules only'
}
