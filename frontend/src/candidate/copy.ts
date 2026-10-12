// Candidate-facing wording. ALL OF THIS IS PLACEHOLDER until Cytonn supplies the approved text
// (master plan R11). Keeping it in one file means swapping it is a one-file change.

/** Shown in the integrity statement (D3), the device notice (D6) and the volunteer brief (D14). */
export const MIC_NOTICE =
  'Keep your microphone on for the whole test. If it is muted for a while you will see a ' +
  'warning which will be shown to your reviewer.'

export const INTEGRITY_TITLE = 'Before you begin'

export const INTEGRITY_POINTS: string[] = [
  'I will take this test on my own, without help from another person.',
  'I will not look up answers, use other websites or applications, or copy or share questions.',
  'My camera and microphone record for the whole test, and my actions in this window are logged.',
  'A person reviews anything unusual. No computer decides the outcome for me.',
  MIC_NOTICE,
]

export const INTEGRITY_CHECKBOX = 'I have read and agree to the statement above.'

export const SELF_REPORT_QUESTION = 'Did you have any technical problems during the test?'
export const SELF_REPORT_NOTE_LABEL = 'What happened? (optional, up to 300 characters)'
export const SELF_REPORT_NOTE_HINT = 'Please do not write your name or contact details.'

export const NOT_SEB_TITLE = 'Safe Exam Browser required'
export const NOT_SEB_BODY =
  'This test can only be taken inside Safe Exam Browser. Please close this window and open ' +
  'the test from the Safe Exam Browser configuration file you were given.'
