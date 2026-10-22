# Scripted actions

Every action a candidate can take that the rules are expected to see, how it is performed, the
flag it should raise and the test that proves it. "Caught 100% of the time" is counted against this
table. Each test drives the real HTTP API (events and heartbeats) on a fake clock and reads the
flags the server computed: `backend/tests/integration/test_scripted_scenarios.py`.

| ID | Action | Expected | Test |
|---|---|---|---|
| S1 | Tab out for 40 s to look something up, then answer correctly after a long hold, on 3 questions | `FOCUS_LOSS` x3 and `LONG_HOLD_CORRECT` x3 at weight 4 (3 + 1 for focus lost during it) | `test_tabbing_out_to_look_something_up_is_caught...` |
| S2 | A very long hold, answered correctly, with no focus loss | `LONG_HOLD_CORRECT` at weight 3 | `test_a_long_hold_on_a_question_answered_correctly...` |
| S3 | Copy the question text | `COPY_ATTEMPT` at weight 3, `detail.length` only; the wording never reaches the table | `test_copying_the_question_is_caught...` |
| S4 | Cut text | `COPY_ATTEMPT` | `test_cutting_counts_as_copying` |
| S5 | Go idle for 90 s, then answer 3 or more in a row correctly and fast | `CORRECT_RUN_AFTER_GAP` at weight 2 | `test_going_idle_then_answering_a_run...` |
| S6 | Lose focus for 3 s (flag) and for 0.5 s (no flag) | `FOCUS_LOSS` for the 3 s only | `test_a_focus_loss_of_a_second_or_more_counts...` |
| S7 | Heartbeats stop for 40 s or more with no drop and no reload | `LOGGING_PROBLEM` at weight 0, its own lane | `test_heartbeats_stopping_for_a_minute...` |
| S8 | Events sent late after being offline | Keep the moment they happened, inside the right question | `test_events_that_arrive_late_keep_the_moment...` |
| S9 | Several correct answers far quicker than the question's usual quick time | `FAST_CORRECT_VS_HISTORY`, only on questions with 30 or more past candidates, labelled `cytonn` or `synthetic` | `backend/tests/unit/test_flag_history.py` |
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
