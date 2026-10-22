# Scripted run in a real browser

> **Status: template. This run has not been done.**

The proposal's first criterion: the rule checks catch scripted actions 100% of the time, with
"one run in a real browser at full screen". The scenario tests already prove that each action,
once it reaches the server as an event, gives the expected flag
([eval/scripted_actions.md](../scripted_actions.md)). This run proves the other half: that a real
browser, doing the real action, produces those events at all.

Date: ____ · Operator: ____ · Chrome version: ____ · Edge version: ____ · Windows version: ____

## How to run it

1. Make a small sitting, for example "Browser run", with a window that includes now. Close any
   other open sitting first. Generate 2 invitations, one for Chrome and one for Edge.
2. Serve the build the pilot uses (`docker compose up -d --build`, then `http://localhost:8080`),
   so the real pre-check and the strict gate are in play.
3. For each browser: open the link, go through the pre-check, **press the full screen button**,
   and do each action below, noting the question number and the clock time.
4. Close the sitting (`close_sitting --force` is fine here) and compute flags:

   ```powershell
   docker compose exec api python -m scripts.jobs close_sitting --sitting "Browser run" --force
   docker compose exec api python -m scripts.jobs compute_flags --sitting "Browser run"
   ```

5. Open each candidate in the reviewer app and fill in the table.

The pace and spread checks (S10) need 8 finished sessions in a closed sitting and are left to the
pilot. S7 needs the heartbeat to stop with nothing to explain it, and the page has no switch for
that, so it stays an API test.

## Results

Fill in **Seen by the page?** from the candidate's event log or the reviewer page, and **Flag
raised** from the flags list.

| ID | Action performed | Chrome: seen / flag raised | Edge: seen / flag raised | Notes |
|---|---|---|---|---|
| S1 | Alt+Tab away for 40 s, come back after a long hold on 3 questions and answer correctly | | | |
| S2 | A hold of 2 minutes or more on one question, no leaving the window, answered correctly | | | |
| S3 | Select the question text and press Ctrl+C | | | |
| S4 | Cut: there is nothing editable to cut from in the page, so note whether the page can produce one at all | | | |
| S5 | Stay idle for 90 s, then answer 3 or more in a row correctly and quickly | | | |
| S6 | Switch away for 3 s (flag) and for under 1 s (no flag) | | | |
| S8 | Go offline for 20 s during a question; check the events keep the time they happened | | | |
| S9 | Several correct answers well under a question's usual quick time (counts only on questions with 30 or more past candidates) | | | |
| S7, S10 | Covered by API and unit tests; S10 also runs in the pilot | n/a | n/a | |

## Must never raise a flag

Do each, once, and check no flag appears.

| Action | Chrome | Edge | Where the reviewer sees it |
|---|---|---|---|
| Leave full screen with Esc and come back | | | `fullscreen_exits` |
| Reload the page | | | `innocent_signals` |
| Turn Wi-Fi off for 20 s | | | `innocent_signals` |
| Right-click, paste | | | logged, not shown |

## What a page cannot see

For each action, whether the page noticed at all, in each browser. This list goes into the
handover as a known limit. The [D2 checklist](../../docs/spikes/browser-findings.md) (checks 8 to 10
in particular) is the fuller version and is still blank.

| Action | Chrome | Edge |
|---|---|---|
| Print Screen | | |
| Windows key, Alt+Tab | | |
| A Windows notification or chat pop-up taking focus | | |
| Clicking on a second monitor while full screen | | |
| A screenshot tool (Snipping Tool) | | |
| A phone photographing the screen | not observable | not observable |

## Result

All of S1 to S6, S8 and S9 raised the expected flag in both browsers: yes / no. Anything that did
not is written up above with the cause.
