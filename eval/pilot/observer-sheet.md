# Observer sheet

For the observers on pilot day. Print one copy per observer. You write down what happens and
when. You do not help anyone and you do not say who has which role.

## Before the sitting

| | |
|---|---|
| Observer | |
| Seats you watch (up to 4) | |
| Time on the operator's laptop at the start (hh:mm:ss) | |
| Time on your own watch or phone at the same moment | |
| Difference in seconds (yours minus the laptop's) | |

Read the operator's laptop clock once, all together, before volunteers start. The record uses the
laptop's clock, so the difference matters when the times are compared later.

## During the sitting

One row for every marked action you see or hear ("mark" said out loud and a raised hand). Write
the time to the second as soon as it happens. If you miss one, write that.

| Seat | Candidate ID | Marked action (tab-out, copy, idle, hold) | Question number | Clock time (hh:mm:ss) | Said "mark"? |
|---|---|---|---|---|---|
| | | | | | |
| | | | | | |
| | | | | | |
| | | | | | |
| | | | | | |
| | | | | | |
| | | | | | |
| | | | | | |
| | | | | | |
| | | | | | |

## Offline volunteers

For each of the two volunteers who go offline:

| Seat | Candidate ID | Wi-Fi off at | Wi-Fi back on at | Anything unusual |
|---|---|---|---|---|
| | | | | |
| | | | | |

## Anything else

Write down anything that went wrong or looked odd, with the seat and the time: a camera that
stopped, a volunteer who closed the tab, an error message. Do not fix it unless the operator asks.

| Seat | Time | What happened |
|---|---|---|
| | | |
| | | |
| | | |

## After the sitting: turning the sheet into the timing result

The operator does this with your sheet.

1. Sign in to the reviewer app and open a candidate from your sheet. Each flag has a **Jump to
   video** button. The label above the player names the flag, such as `F3 Copy attempt`.
2. Match each flag to a row on your sheet by candidate and time. Note the difference between the
   flag's time and your clock time, once your clock difference is taken off. Both should agree to
   about a second or two.
3. Press **Jump to video**. The player starts 5 seconds before the flag. Watch for the moment the
   volunteer says "mark" and raises a hand, and read the player's time at that moment. That is
   `cue_s`.
4. Add a row to `eval/pilot/cues.csv` (make the file; it is not kept in the repository ahead of
   time):

   ```csv
   candidate_id,flag_id,segment,cue_s
   cand-031,F3,0,5.4
   ```

   `segment` is 0 unless the volunteer's camera restarted or the page was reloaded, in which case
   the jump says which part it landed in.
5. Run the check:

   ```powershell
   docker compose cp eval/pilot/cues.csv api:/tmp/cues.csv
   docker compose exec api python -m scripts.jobs video_offset --sheet /tmp/cues.csv
   ```

   It prints, for every row, how far the cue is from where the jump should put it. The target is
   within 2 seconds.

A flag that says there is no video at that moment is a result too: write it down and say why if
you know (a camera drop, a page reload, an upload that never finished).
