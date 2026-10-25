// Reviewer-facing wording. Nothing here may read as a verdict: the AI ranks and explains, a person
// decides.

import type {
  AiStatus,
  Band,
  DecisionOutcome,
  EmailState,
  LogQuestion,
  OutcomeStatus,
  SessionStatus,
} from '../lib/reviewTypes'

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

export const RETENTION_NOTE =
  'The newest decision counts. Video is deleted 30 days after it, and every decision and video ' +
  'view is written to the audit log.'

export const FLAG_LABELS: Record<string, string> = {
  FOCUS_LOSS: 'Focus lost',
  COPY_ATTEMPT: 'Copy or cut attempt',
  SCREENSHOT_KEY: 'Screenshot key pressed',
  LONG_HOLD_CORRECT: 'Long hold with focus lost, answered correctly',
  CORRECT_RUN_AFTER_GAP: 'Quick run of correct answers after a gap',
  PACE_OUTLIER: 'Pace far from the sitting',
  SPREAD_OUTLIER: 'Answer-time spread far from the sitting',
  LOGGING_PROBLEM: 'Logging problem (heartbeat gap)',
}

export const DETAIL_LABELS: Record<string, string> = {
  target: 'where',
  length: 'length copied (characters)',
  combo: 'keys pressed',
  time_s: 'time on the question (s)',
  own_median_s: "candidate's own median (s)",
  gap_s: 'gap before the run (s)',
  run_length: 'correct in a row',
  mean_s: 'average time per question after the gap (s)',
  focus_lost_s: 'focus lost for (s)',
  robust_z: 'robust z',
  direction: 'direction',
  heartbeat_gap_s: 'no heartbeat for (s)',
}

export const QUEUE_EMPTY =
  'No flagged candidates in this sitting yet. A candidate\'s flags are worked out as they finish, ' +
  'and again for the whole sitting when it is closed. "Everyone" shows candidates who have no flags.'
export const EVERYONE_NOTE =
  'Everyone who opened the test in this sitting, flagged or not. The queue is the work list; this ' +
  'is how to find anyone else. Video stays closed unless they are in the queue or shortlisted.'
export const VIDEO_CLOSED =
  'Video stays closed for candidates who are not in the review queue. Add them to the shortlist ' +
  'if you need to open it; the shortlisting is written to the audit log.'

export const STATUS_LABELS: Record<SessionStatus, string> = {
  created: 'Opened, not started',
  in_progress: 'Sitting now',
  finished: 'Finished',
}

export const LOG_NOTE =
  'Everything the candidate\'s page reported, in server time. Most lines are not flags: the rules ' +
  'choose which of them count, and a person decides what they mean.'

/** Plain names for what the page reports. They describe; none of them is an accusation. */
export const EVENT_LABELS: Record<string, string> = {
  page_load: 'Page loaded',
  reload: 'Page reloaded',
  question_opened: 'Question opened',
  answered: 'Answered',
  skipped: 'Skipped',
  focus_lost: 'Left the test window',
  focus_returned: 'Came back to the test window',
  visibility_hidden: 'Tab hidden',
  visibility_visible: 'Tab visible again',
  copy_attempt: 'Copy attempt',
  cut_attempt: 'Cut attempt',
  paste_attempt: 'Paste attempt',
  screenshot_attempt: 'Screenshot key pressed',
  contextmenu_attempt: 'Right-click menu opened',
  idle_start: 'Stopped interacting',
  idle_end: 'Started interacting again',
  connection_lost: 'Connection lost',
  connection_restored: 'Connection restored',
  device_info: 'Camera and microphone reported',
  mic_muted: 'Microphone muted',
  mic_unmuted: 'Microphone unmuted',
  mic_silent_start: 'Microphone went quiet',
  mic_silent_end: 'Microphone sound returned',
  camera_dropped: 'Camera dropped',
  track_ended: 'Camera or microphone stopped',
  fullscreen_exited: 'Left full screen',
  fullscreen_entered: 'Entered full screen',
  recording_started: 'Recording started',
  upload_incomplete: 'Upload incomplete',
}

export const LOG_DETAIL_LABELS: Record<string, string> = {
  length: 'length (characters)',
  duration_s: 'lasted (s)',
  camera_label: 'camera',
  mic_label: 'microphone',
  segment: 'part',
  missing: 'chunks missing',
  kind: 'track',
}

export const RESULT_LABELS: Record<LogQuestion['result'], string> = {
  correct: 'Correct',
  wrong: 'Wrong',
  skipped: 'Skipped',
  unanswered: 'Not answered',
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

// ---- results and the outcomes list. Plain words for staff; a status is where a candidate stands,
// never a verdict from the system.

export const STATUS_PILLS: Record<OutcomeStatus, { label: string; tone: string }> = {
  invited: { label: 'Not started', tone: 'plain' },
  in_progress: { label: 'Sitting now', tone: 'moderate' },
  waiting_review: { label: 'Waiting for review', tone: 'high' },
  in_review: { label: 'Reviewed, no result yet', tone: 'moderate' },
  ready: { label: 'Ready for a result', tone: 'plain' },
  passed: { label: 'Passed', tone: 'ok' },
  failed_score: { label: 'Below pass mark', tone: 'warn' },
  failed_review: { label: 'Failed after review', tone: 'warn' },
  under_appeal: { label: 'Under appeal', tone: 'moderate' },
  incomplete: { label: 'Did not finish', tone: 'plain' },
}
export const STATUS_ORDER = Object.keys(STATUS_PILLS) as OutcomeStatus[]

export const EMAIL_PILLS: Record<EmailState, { label: string; tone: string }> = {
  none: { label: 'Not sent', tone: 'plain' },
  queued: { label: 'Sending', tone: 'moderate' },
  sent: { label: 'Sent', tone: 'ok' },
  failed: { label: 'Failed to send', tone: 'warn' },
}

/** Why a result cannot be recorded right now, in the words the panel uses. */
export const BLOCKED_BY: Record<string, string> = {
  not_finished: 'This candidate has not finished the test, so there is no result to send.',
  already_emailed: 'A result email has already gone to this candidate and cannot be taken back.',
  no_email: 'There is no email address on file for this candidate, so nothing can be sent.',
  review_first: 'This candidate is flagged. Record your decision above first, then send the result.',
}

export const RESULT_NOTE =
  'You decide, the system sends. A pass or a fail goes to the candidate as an email at once and ' +
  'cannot be taken back. A failed candidate is told the reason you pick and how to appeal.'
