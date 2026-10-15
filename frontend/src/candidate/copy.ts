// Candidate-facing wording. ALL OF THIS IS PLACEHOLDER until Cytonn supplies the approved text
// (master plan R11). Keeping it in one file means swapping it is a one-file change.

import type { DeviceErrorKind } from '../lib/devices'

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

/** Under every dead end, so nobody is left without a next step. Cytonn supplies the real contact. */
export const HELP_CONTACT =
  'If this keeps happening, contact the person who sent your invitation.'

// ---- code entry

export const START_ERRORS: Record<string, string> = {
  invalid_invitation:
    'That code is not valid. Check it against your invitation and type it again. Capital ' +
    'letters and the dash do not matter.',
  no_open_sitting:
    'This test is not open right now. Check the date and time on your invitation and come ' +
    'back then.',
}
export const START_FALLBACK_ERROR = 'Something went wrong. Please try again.'

export const NOT_SEB_TITLE = 'Safe Exam Browser required'
export const NOT_SEB_BODY =
  'This test can only be taken inside Safe Exam Browser. This window is a normal browser.'
export const NOT_SEB_STEPS: string[] = [
  'Close this window.',
  'Open the Safe Exam Browser file you were given. It ends in .seb.',
  'Type your invitation code when the test opens.',
]
export const NOT_SEB_HELP =
  'If you do not have the file, or it will not open, contact the person who sent your invitation.'

// ---- device pre-check (D6) and the mid-test warning

export const DEVICE_NOTICE_TITLE = 'Check your camera and microphone'

export const DEVICE_NOTICE_POINTS: string[] = [
  'Use a Windows or Mac computer, or an iPad, with a working webcam and microphone. ' +
    'Android phones and Chromebooks cannot sit this test. It has been tested on Windows.',
  'Your camera and microphone record for the whole test. Recording uses about 80 MB an ' +
    'hour, so please use Wi-Fi rather than mobile data.',
  MIC_NOTICE,
]

export const DEVICE_NOTICE_CHECKBOX = 'I understand, and I am ready to check my devices.'

export const DEVICE_ERRORS: Record<DeviceErrorKind, string> = {
  denied:
    'The camera or microphone is blocked. Allow them in the Safe Exam Browser settings and in ' +
    'your system privacy settings, then try again.',
  not_found: 'No camera or microphone was found. Plug one in or switch it on, then try again.',
  in_use:
    'The camera or microphone is being used by another program. Close that program, then try again.',
  unknown: 'Could not start the camera and microphone. Please try again.',
}

export const MIC_PROMPT = 'Say your name out loud.'
export const MIC_MUTED_MESSAGE =
  'Your microphone looks muted. Unmute it (check the headset button, the keyboard key and the ' +
  'system privacy switch), then try again.'
export const MIC_QUIET_MESSAGE =
  'We could not hear you. Speak a little louder or move closer to the microphone, then try again.'

/** Non-blocking: shown above the question while the microphone looks muted or silent. */
export const MIC_BANNER =
  'Your microphone looks muted or silent. Please unmute it and keep it on for the whole test. ' +
  'Your test continues.'

// ---- upload and complaints (D8)

export const UPLOAD_TITLE = 'Sending your recording'
export const UPLOAD_KEEP_OPEN =
  'Please keep this window open until the upload finishes. It can take a few minutes on a ' +
  'slow connection.'
export const UPLOAD_DONE = 'Everything has been uploaded. You can finish now.'
export const UPLOAD_STUCK =
  'The upload is not moving. You can quit now. A person will see that your upload was ' +
  'incomplete, and you can tell us what happened with the form below.'

// ---- the last page

export const QUIT_TITLE = 'You have finished'
export const QUIT_BODY = 'This window may close by itself. If it does not, press Leave.'
export const QUIT_LEAVE = 'Leave'
export const QUIT_STILL_OPEN = 'If the window is still open after you press Leave, close it yourself.'

export const COMPLAINT_TITLE = 'Tell us what went wrong'
export const COMPLAINT_NOTE_LABEL = 'What happened? (up to 1000 characters)'
export const COMPLAINT_THANKS =
  'Thank you. A person will read this. It will not count against you.'
export const COMPLAINT_CATEGORIES: { value: 'camera' | 'upload' | 'other'; label: string }[] = [
  { value: 'camera', label: 'My camera or microphone stopped working' },
  { value: 'upload', label: 'My recording would not upload' },
  { value: 'other', label: 'Something else' },
]
