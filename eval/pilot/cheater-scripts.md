# Cheater scripts

For the operator, who briefs the six volunteers who act out cheating. Print one card per person
and hand it over privately. Nobody else, including the honest volunteers and the other cheaters,
sees which card went to whom.

This is what the rule checks are measured against. The scripts are fixed in advance and are not
tuned to the thresholds. If a script does not get caught, that is a result, and it goes in the
pilot report as it is.

## What every cheater does

- Use your own laptop, Chrome or Edge, full screen, the way an honest candidate would.
- Outside your script, take the test normally.
- Each action below is a **marked action**. At the moment you do it, say "mark" out loud and
  raise a hand into the camera picture for a second. The video then shows when it happened. The
  observer writes down the clock time.
- Only do what your card says. No second device, no help from another person, no virtual camera,
  no muting the microphone. None of those are part of this pilot.
- If you cannot do a step (for example you do not know an answer), do the rest and tell the
  observer afterwards.

The scripts assume a test of at least 12 questions and about 30 minutes. If the sitting is
shorter, tell the operator before the day: C1 and C6 need minutes of extra time on single
questions.

## Cards

### C1: looks things up

On **4 different questions**:

1. Read the question.
2. Switch to another window (Alt+Tab, or click a second window) as if to search for the answer.
   Stay away for about 40 seconds. Marked action: the moment you switch away.
3. Come back to the test and answer. Keep the total time on that question above 2 minutes, so
   think about it for a while after you return.

Expected: `FOCUS_LOSS` on each, `LONG_HOLD_CORRECT` on those you answer correctly.

### C2: copies the questions

On **3 different questions**: select the question text with the mouse and press Ctrl+C. Marked
action: the moment you press Ctrl+C. Do not paste it anywhere and do not switch windows. Then
answer in your normal time.

Expected: `COPY_ATTEMPT` on each.

### C3: goes quiet, then runs

1. On one question, stop touching the keyboard and mouse for about 90 seconds. Marked action: the
   moment you stop. Stay in the window.
2. Then answer the **next 4 questions in a row**, each in 15 seconds or less, and try to get
   each one right.

Expected: `CORRECT_RUN_AFTER_GAP`.

### C4: the same time on every answer

Spend about **20 seconds on every question**, all of them, as evenly as you can. Use a watch or
a clock you can see. Do not slow down for hard ones. No marked actions: this one is judged
against the rest of the sitting, after it closes.

Expected: `SPREAD_OUTLIER` (needs 8 or more finished candidates).

### C5: fast and right

Answer **at least 8 questions in 6 to 10 seconds each**, trying to get them right. No marked
actions.

Expected: possibly `PACE_OUTLIER` (and `SPREAD_OUTLIER`), judged against the rest of the sitting.
Nothing is judged against past candidates any more, so a fast stretch on its own raises no
per-person flag: `CORRECT_RUN_AFTER_GAP` needs a gap (a tab-out of 5 s or more, or an idle stretch
of a minute) straight before the quick run.

### C6: a bit of everything

On three different questions:

- **One tab-out** of about 40 seconds. Marked action: the moment you switch away.
- **One copy** of the question text with Ctrl+C. Marked action: the moment you press it.
- **One long hold**: stay on a question, in the window, for at least 2 minutes, then answer.
  Marked action: the moment you open that question.

Expected: `FOCUS_LOSS`, `COPY_ATTEMPT` and `LONG_HOLD_CORRECT`, and a higher rule score from
having three kinds.

## Why C4 and C5 have no marked actions

The plan asked every cheater for 5 or 6 marked actions for the video-timing check. C4 and C5 are
caught by comparing them with the sitting or with past candidates, and a focus loss added to them
would hand them a flag the script does not produce, so their result would no longer say whether
the pace and history rules work. The timing check uses the marked actions of C1, C2, C3 and C6,
which come to far more than 5 or 6.

## The two honest volunteers who go offline

Not a cheater card. Tell two honest volunteers privately:

1. Around question 6, stop and turn Wi-Fi off. Note the time, or tell the observer.
2. Leave it off for **2 minutes** by the clock. Do not press anything in the test meanwhile.
3. Turn Wi-Fi back on and carry on.

Expected: no flag (a dropped connection is context), and every video chunk still arrives. This
is the "no video chunks lost" check.

## After the sitting

The operator checks each planted action against the record. If a cheater's script did not run as
written (answers were wrong, they forgot a step), the report says so under that candidate. A wrong
answer is not a missed detection: the rules that look for correct answers cannot fire on a wrong
one.
