// Candidate-facing wording, kept in one file so changing it is a one-file change.

import type { DeviceErrorKind } from '../lib/devices'

/** Shown in the integrity statement, the device notice and the volunteer brief. */
export const MIC_NOTICE =
  'Keep your microphone on for the whole test. If it is muted for a while you will see a ' +
  'warning which will be shown to your reviewer.'

/** Shown in place of the microphone step while that check is switched off for testing. */
export const MIC_CHECK_OFF_NOTE =
  'The microphone check is switched off for this test run, so your microphone is not tested.'

/** Under every dead end, so nobody is left without a next step. */
export const HELP_CONTACT = 'If this keeps happening, contact the person who sent your invitation.'

// ---- code entry

export const START_LEAD =
  'Enter the invitation code and the email address it was sent to. If you have already chosen a ' +
  'password, your email and password are enough.'
export const START_LEAD_CREATING =
  'That is right. Now choose a password. Next time, your email and password are enough.'
export const FORGOT_PASSWORD =
  'Forgot your password? Ask the person who invited you to send you a new link.'
export const PASSWORDS_DIFFER = 'The two passwords are not the same. Type them again.'

export const START_ERRORS: Record<string, string> = {
  invalid_invitation:
    'That code, email or password does not match an invitation. Check them against the message ' +
    'that invited you and type them again. Capital letters and the dash in the code do not matter.',
  password_too_short: 'Your password needs at least 8 characters.',
  password_too_long: 'That password is too long. Please use 72 characters or fewer.',
  // A second device was opened while the test is running on the first.
  test_open_elsewhere:
    'Your test is open on another device. If that is not you, tell the person who invited you. ' +
    'If your browser crashed, wait a minute and try again.',
  // The sitting has closed, its time has passed, or there is none: not early, so no "come back".
  no_open_sitting:
    'This test is not open right now. It may have closed. If you think it should still be ' +
    'open, contact the person who sent your invitation.',
}
/** Early, not late: the code is right and the test has a date, so say it. */
export const notOpenYet = (when: string) =>
  `This test has not opened yet. It opens on ${when}. Please come back then with the same code.`
export const START_FALLBACK_ERROR = 'Something went wrong. Please try again.'

// ---- the pre-check: everything the exam asks for, one step at a time

export const PRECHECK_TITLE = 'Get ready'
export const PRECHECK_LEAD =
  'Six quick steps. We ask for everything the test needs now, so nothing interrupts you once it starts.'

export const STEP_TITLES = {
  notice: 'Before you start',
  notifications: 'Turn off notifications',
  permissions: 'Allow camera and microphone',
  devices: 'Check your camera and microphone',
  fullscreen: 'Go full screen',
  ready: 'Ready',
} as const

export const DEVICE_NOTICE_POINTS: string[] = [
  'Use a Windows or Mac laptop or desktop with a current Chrome or Edge, and a working webcam ' +
    'and microphone. Phones, tablets and Chromebooks cannot sit this test, and a private window ' +
    'is not supported. It has been tested on Windows.',
  'Your camera and microphone record for the whole test. Recording uses about 40 to 50 MB ' +
    'an hour, and never more than about 80 MB an hour, so please use Wi-Fi rather than ' +
    'mobile data.',
  'The test runs full screen. Leaving full screen, or switching to another window, is noted and ' +
    'shown to the person who reviews your test.',
  MIC_NOTICE,
]
export const DEVICE_NOTICE_CHECKBOX = 'I understand, and I am ready to check my devices.'

export const NOTIFICATIONS_LEAD =
  'A pop-up from a chat, an email or a calendar can pull the screen away from the test, and ' +
  'your reviewer would see that as time away from the page. Switch them off before you start.'
export const NOTIFICATIONS_HOW: string[] = [
  'Windows: open Focus assist (or Do not disturb) and switch it on.',
  'Mac: switch on a Focus (Do Not Disturb).',
  'Close Teams, Slack, WhatsApp Web, your email and your calendar.',
  'If you have allowed other websites to send notifications, pause them in your browser.',
]
export const NOTIFICATIONS_CHECKBOX = 'I have turned off notifications.'
export const NOTIFICATIONS_NOTE =
  'A web page cannot see your notification settings, so we are relying on you. Your answer is ' +
  'kept with your test.'

export const PERMISSIONS_LEAD =
  'Your browser will ask once. Choose Allow so the test can see and hear you. They are used only ' +
  'during the test.'
export const PERMISSION_STATE_LABELS = {
  unknown: 'Not asked yet',
  prompt: 'Not asked yet',
  asking: 'Waiting for you to choose',
  granted: 'Allowed',
  denied: 'Blocked',
} as const
export const PERMISSION_BLOCKED_HELP: string[] = [
  'Click the camera or lock icon at the left of the address bar.',
  'Set Camera and Microphone to Allow.',
  'Press Try again. If it is still blocked, check the Camera and Microphone privacy settings in ' +
    'Windows (Settings, Privacy) or on your Mac (System Settings, Privacy & Security).',
]

export const DEVICE_ERRORS: Record<DeviceErrorKind, string> = {
  denied:
    'The camera or microphone is blocked. Allow them in your browser (the icon at the left of ' +
    'the address bar) and in your system privacy settings, then try again.',
  not_found: 'No camera or microphone was found. Plug one in or switch it on, then try again.',
  in_use:
    'The camera or microphone is being used by another program. Close that program, then try again.',
  unknown: 'Could not start the camera and microphone. Please try again.',
}

export const CAPTURE_PROBLEMS = {
  insecure:
    'This address is not secure (it does not start with https), so your browser will not give ' +
    'the page your camera. Open the link you were sent, or contact the person who sent it.',
  no_media: 'This browser cannot use the camera for web pages. Please use a current Chrome or Edge.',
} as const

export const UNSUPPORTED_BROWSER =
  'This test has only been tested on Chrome and Edge on a laptop or desktop. You can carry on, ' +
  'but if something does not work, switch to one of those.'

export const MIC_PROMPT = 'Say your name out loud.'
export const MIC_MUTED_MESSAGE =
  'Your microphone looks muted. Unmute it (check the headset button, the keyboard key and the ' +
  'system privacy switch), then try again.'
export const MIC_QUIET_MESSAGE =
  'We could not hear you. Speak a little louder or move closer to the microphone, then try again.'

export const FULLSCREEN_LEAD =
  'The test runs full screen. Press the button below and your browser switches over; it asks ' +
  'nothing else.'
export const FULLSCREEN_UNSUPPORTED =
  'This browser does not allow full screen. Please use a current Chrome or Edge.'
export const FULLSCREEN_EXIT_HINT = 'You can leave full screen with Esc, but you will be asked to come back.'

export const READY_LEAD = 'Everything the test needs is in place.'

/** Covers the question while the page is not full screen. The clock keeps running. */
export const FULLSCREEN_COVER_TITLE = 'Return to full screen'
export const FULLSCREEN_COVER_BODY =
  'You left full screen. Your test is still running and the clock has not stopped. Press the ' +
  'button to carry on. Leaving full screen is noted for your reviewer.'

/** Non-blocking: shown above the question while the microphone looks muted or silent. */
export const MIC_BANNER =
  'Your microphone looks muted or silent. Please unmute it and keep it on for the whole test. ' +
  'Your test continues.'

// ---- the statement and the end of the test

export const INTEGRITY_TITLE = 'Before you begin'
export const INTEGRITY_POINTS: string[] = [
  'I will take this test on my own, without help from another person.',
  'I will not look up answers, use other websites or applications, take screenshots, or copy or share questions.',
  'My camera and microphone record for the whole test, and my actions in this window are ' +
    'logged, including leaving full screen and pressing a screenshot key.',
  'A person reviews anything unusual. No computer decides the outcome for me.',
  MIC_NOTICE,
]
export const INTEGRITY_CHECKBOX = 'I have read and agree to the statement above.'

export const SELF_REPORT_QUESTION = 'Did you have any technical problems during the test?'
export const SELF_REPORT_NOTE_LABEL = 'What happened? (optional, up to 300 characters)'
export const SELF_REPORT_NOTE_HINT = 'Please do not write your name or contact details.'

// ---- starting the recording, and a camera lost during the test

export const RECORDING_STARTING = 'Starting your recording...'

// An AI sitting writes each candidate's questions while they read this page. Their time has not
// started, and the page says so every time, so waiting never feels like losing time.
export const PAPER_PREPARING = 'Preparing your questions'
export const PAPER_PREPARING_NOTE =
  'Your time has not started. The button below opens up as soon as your questions are ready.'
export const PAPER_FAILED =
  'We could not prepare your questions. Your time has not started. Try again, and if it keeps ' +
  'failing, tell the person who invited you.'
export const PAPER_RETRY = 'Try again'
// After ten minutes of waiting the candidate may ask again. Their time still has not started.
export const PAPER_SLOW =
  'This is taking longer than usual. Your time has still not started. You can ask for your ' +
  'questions again; whatever is already written is kept.'
export const PAPER_SLOW_RETRY = 'Ask for my questions again'
// Shown on the "start the test" page. None of them has started the clock: the test begins only
// once the recording is safely with us.
export const RECORDING_PROBLEMS = {
  no_devices:
    'We could not reach your camera and microphone. Go back to the check, allow them, and try ' +
    'again. Your time has not started.',
  unsupported:
    'This browser cannot record. Please open the test in the latest Chrome or Edge on a Windows ' +
    'or Mac computer. Your time has not started.',
  slow:
    'Your recording has not reached us yet. Check your connection and press the button again. ' +
    'Your time has not started.',
  not_confirmed:
    'We could not confirm your recording yet. Make sure your camera is on, then press the ' +
    'button again. Your time has not started.',
} as const
export const CAMERA_LOST_BANNER =
  'Your camera or microphone stopped. We are trying to reconnect. Your test carries on and the ' +
  'clock keeps running. Check the cable, and that no other program is using the camera.'

// ---- upload and complaints (D8)

export const UPLOAD_TITLE = 'Sending your recording'
export const UPLOAD_KEEP_OPEN =
  'Please keep this tab open until the upload finishes. It can take a few minutes on a slow ' +
  'connection.'
export const UPLOAD_RESUME_HINT =
  'If you close this tab first, open your invitation link again within 48 hours and the rest ' +
  'will be sent from this computer.'
export const UPLOAD_CLOSED =
  'The time for sending this recording has passed, so no more can be sent. You can tell us ' +
  'what happened with the form below.'
export const UPLOAD_DONE = 'Everything has been uploaded. You can finish now.'

export const RESUME_TITLE = 'Finish sending your recording'
export const RESUME_LEAD =
  'Sign in the way you did for the test: the invitation code and your email, or your email and ' +
  'password. Use the same computer and browser, so the rest of your recording can be found and sent.'
export const RESUME_ERRORS: Record<string, string> = {
  nothing_to_resume:
    'There is no finished test waiting for this code. If your test has not opened yet, come ' +
    'back at the time on your invitation.',
  resume_window_closed:
    'The 48 hours for sending a recording have passed. Please contact the person who sent your ' +
    'invitation and tell them what happened.',
}
export const UPLOAD_STUCK =
  'The upload is not moving. You can finish now. A person will see that your upload was ' +
  'incomplete, and you can tell us what happened with the form below.'

export const FINISHED_TITLE = 'You are finished'
export const FINISHED_BODY = 'Thank you. You can close this window.'
// Only while the page is still in full screen, and only once the recording has been sent.
export const FINISHED_LEAVE = 'Press Esc to leave full screen.'
export const FINISHED_LEAVE_BUTTON = 'Exit full screen'

export const COMPLAINT_TITLE = 'Tell us what went wrong'
export const COMPLAINT_NOTE_LABEL = 'What happened? (up to 1000 characters)'
export const COMPLAINT_THANKS = 'Thank you. A person will read this. It will not count against you.'
export const COMPLAINT_CATEGORIES: { value: 'camera' | 'upload' | 'other'; label: string }[] = [
  { value: 'camera', label: 'My camera or microphone stopped working' },
  { value: 'upload', label: 'My recording would not upload' },
  { value: 'other', label: 'Something else' },
]
