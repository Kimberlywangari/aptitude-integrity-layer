# Scripted actions

Every action a candidate can take that the rules are expected to see, how it is performed, the
flag it should raise and the test that proves it. "Caught 100% of the time" is counted against this
table. Each test drives the real HTTP API (events and heartbeats) on a fake clock and reads the
flags the server computed: `backend/tests/integration/test_scripted_scenarios.py`.

| ID | Action | Expected | Test |
|---|---|---|---|
| S1 | Tab out for 40 s to look something up, then answer correctly after a long hold, on 3 questions | `FOCUS_LOSS` x3 and `LONG_HOLD_CORRECT` x3 at weight 4, `detail.focus_lost_s` 40 | `test_tabbing_out_to_look_something_up_is_caught...` |
| S2 | A very long hold, answered correctly, with focus on the page the whole time (or away for 2 s or less) | **No flag**: a long hold needs focus lost for more than 2 s | `test_a_long_hold_with_focus_on_the_page...`, `test_a_long_hold_needs_more_than_two_seconds_away` |
| S3 | Copy the question text | `COPY_ATTEMPT` at weight 3, `detail.length` only; the wording never reaches the table | `test_copying_the_question_is_caught...` |
| S4 | Cut text | `COPY_ATTEMPT` | `test_cutting_counts_as_copying` |
| S5 | Go idle for 90 s, then answer 3 or more in a row correctly and fast (under half their usual time each) | `CORRECT_RUN_AFTER_GAP` at weight 2, with `mean_s` and `own_median_s` | `test_going_idle_then_answering_a_run...` |
| S5b | The same gap, then carry on correctly at their usual pace | **No flag** | `test_a_run_after_a_gap_at_the_candidates_usual_pace_is_not_flagged` |
| S5c | Answer 3 or more in a row, each in under 20 s, without leaving the page (a second device) | `FAST_RUN` at weight 1, one flag per unbroken run, with `answers_in_a_row` and `answers_mean_s` | `test_answering_three_in_a_row_in_under_twenty_seconds...` |
| S5d | Answer a question of 600 or more characters correctly in under 20 s | `LONG_FAST_CORRECT` at weight 0.5, with `time_s` and `question_chars` | `test_long_questions_answered_correctly_in_under_twenty_seconds...` |
| S5e | Answer a hard question correctly in under 15 s | `HARD_FAST_CORRECT` at weight 0.5; never fires on questions with no difficulty (the Cytonn bank) | `backend/tests/unit/test_flag_rules.py` |
| S5f | Take about the same time on 3 or more hard questions as on 3 or more easy ones (hard median under 1.2 x easy, and under 30 s) | `FLAT_PACE` at weight 0.5; same limit on difficulty | `backend/tests/unit/test_flag_rules.py` |
| S6 | Lose focus for 3 s (flag) and for 0.5 s (no flag) | `FOCUS_LOSS` for the 3 s only | `test_a_focus_loss_of_a_second_or_more_counts...` |
| S7 | Heartbeats stop for 40 s or more with no drop and no reload | `LOGGING_PROBLEM` at weight 0, its own lane | `test_heartbeats_stopping_for_a_minute...` |
| S8 | Events sent late after being offline | Keep the moment they happened, inside the right question | `test_events_that_arrive_late_keep_the_moment...` |
| S9 | (removed 23 Oct 2026) answers far quicker than past candidates' | No rule compares a candidate with past candidates any more | n/a |
| S10 | A pace or spread far from the rest of a closed sitting of 8 or more | `PACE_OUTLIER` / `SPREAD_OUTLIER` | `backend/tests/unit/test_flag_rules.py` |

## Must never raise a flag

These are things a page cannot stop and an honest candidate can do. They appear to a reviewer as
context. `test_an_honest_run_with_every_problem_a_page_cannot_prevent_raises_nothing` does all of
them in one run and expects no flag at all.

| Action | Where the reviewer sees it |
|---|---|
| A dropped connection and a page reload | `innocent_signals` |
| The camera dropping, a muted or silent microphone | `innocent_signals`, `mic_silence` |
| Leaving full screen, pasting, opening the context menu | `fullscreen_exits` (the rest are logged, not shown) |

## Not observable by a page

Print Screen, some operating-system shortcuts and a second device are invisible to a web page. The
real-browser run (plan D14) records, for each action in Chrome and Edge, whether the page could see
it at all, and lists the ones it could not here.
