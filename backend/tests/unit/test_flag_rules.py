"""The rule flags, one rule at a time. Each has a case that fires, a case just short of the
threshold, a case exactly at it, and one where an innocent explanation is present."""

from datetime import UTC, datetime, timedelta

from app.services.flags import rules
from app.services.flags.config import FlagConfig
from app.services.flags.scoring import ScoredFlag, is_logging_only, score_flags

T0 = datetime(2026, 10, 14, 9, 0, 0, tzinfo=UTC)
CFG = FlagConfig()


def at(seconds: float) -> datetime:
    return T0 + timedelta(seconds=seconds)


def answer(position, opened, took, correct=True, difficulty=None, skipped=False, length=None):
    return rules.Answer(
        position=position,
        question_id=f"Q{position:03d}",
        difficulty=difficulty,
        opened_at=at(opened),
        answered_at=at(opened + took),
        correct=correct,
        skipped=skipped,
        length=length,
    )


def paper(*times, correct=True):
    """Consecutive questions answered in the given times, 1 s apart."""
    items, cursor = [], 0.0
    for position, took in enumerate(times, start=1):
        items.append(answer(position, cursor, took, correct=correct))
        cursor += took + 1
    return items


def ev(kind, seconds, **payload):
    return rules.Ev(kind, at(seconds), payload)


# ------------------------------------------------------------------------------ focus loss


def test_a_loss_of_one_second_counts_and_one_just_under_does_not():
    answers = paper(60)
    exact = rules.focus_loss_flags([rules.Span(at(10), at(11))], answers, CFG)
    short = rules.focus_loss_flags([rules.Span(at(10), at(10.9))], answers, CFG)
    assert [d.kind for d in exact] == ["FOCUS_LOSS"]
    assert exact[0].weight == 0.5
    assert exact[0].position == 1
    assert exact[0].detail == {"focus_lost_s": 1}
    assert short == []


def test_only_losses_of_a_second_or_more_are_counted_by_any_rule():
    spans = [rules.Span(at(1), at(1.5)), rules.Span(at(5), at(6)), rules.Span(at(9), at(14))]
    assert [s.duration_s for s in rules.counted_losses(spans, CFG)] == [1.0, 5.0]
    assert rules.lost_seconds(spans, at(0), at(10)) == 0.5 + 1.0 + 1.0  # clipped to the window


def test_pairs_a_loss_with_the_next_return_and_runs_an_unreturned_loss_to_the_end():
    events = [ev("focus_lost", 10), ev("focus_returned", 25), ev("focus_lost", 40)]
    spans = rules.focus_losses(events, at(100))
    assert [(s.start, s.end) for s in spans] == [(at(10), at(25)), (at(40), at(100))]
    assert rules.focus_losses([ev("focus_returned", 5)], at(100)) == []


# ------------------------------------------------------------------------------ copy attempts


def test_each_copy_or_cut_is_a_flag_and_only_the_length_is_kept():
    events = [
        ev("copy_attempt", 5, length=212, text="the question text"),
        ev("cut_attempt", 70, length=40),
        ev("paste_attempt", 80),
    ]
    drafts = rules.copy_attempt_flags(events, paper(60, 60), CFG)
    assert [d.kind for d in drafts] == ["COPY_ATTEMPT", "COPY_ATTEMPT"]
    assert all(d.weight == 3 for d in drafts)
    assert drafts[0].detail == {"target": "question_text", "length": 212}
    assert "text" not in drafts[0].detail
    assert [d.position for d in drafts] == [1, 2]


def test_each_screenshot_key_press_is_a_flag_of_two_points_and_nothing_else_is():
    events = [
        ev("screenshot_attempt", 5, combo="PrintScreen"),
        ev("screenshot_attempt", 70, combo="Win+Shift+S"),
        ev("copy_attempt", 80, length=3),
        ev("paste_attempt", 90),
    ]
    drafts = rules.screenshot_key_flags(events, paper(60, 60), CFG)
    assert [d.kind for d in drafts] == ["SCREENSHOT_KEY", "SCREENSHOT_KEY"]
    assert all(d.weight == 2 for d in drafts)
    assert [d.detail for d in drafts] == [{"combo": "PrintScreen"}, {"combo": "Win+Shift+S"}]
    assert [d.position for d in drafts] == [1, 2]


# ---------------------------------------------------------------------------- long hold, correct


def away(start, length):
    """A focus loss that starts `start` seconds in and lasts `length` seconds."""
    return rules.Span(at(start), at(start + length))


def test_long_hold_fires_above_the_limit_and_not_at_it():
    # five others at 30 s: the limit is max(3 x 30, 30 + 45) = 90 s
    others = paper(30, 30, 30, 30, 30)
    just_over = [*others, answer(6, 200, 91)]
    exactly = [*others, answer(6, 200, 90)]
    lost = [away(210, 20)]

    fired = rules.long_hold_correct_flags(just_over, lost, CFG)
    assert [d.kind for d in fired] == ["LONG_HOLD_CORRECT"]
    assert fired[0].weight == 4
    assert fired[0].position == 6
    assert fired[0].detail == {"time_s": 91, "own_median_s": 30, "focus_lost_s": 20}
    assert rules.long_hold_correct_flags(exactly, lost, CFG) == []


def test_the_extra_45_seconds_wins_when_the_median_is_small():
    # median 10 s: 3 x 10 = 30 but 10 + 45 = 55, so 55 s is the limit
    others = paper(10, 10, 10, 10, 10)
    lost = [away(110, 20)]
    assert rules.long_hold_correct_flags([*others, answer(6, 100, 55)], lost, CFG) == []
    assert len(rules.long_hold_correct_flags([*others, answer(6, 100, 56)], lost, CFG)) == 1


def test_the_line_is_capped_because_a_question_closes_at_105_seconds():
    # median 50 s: 3 x 50 = 150 s could never be reached, so the line is the 90 s cap
    others = paper(50, 50, 50, 50, 50)
    lost = [away(260, 20)]
    assert len(rules.long_hold_correct_flags([*others, answer(6, 250, 100)], lost, CFG)) == 1
    assert rules.long_hold_correct_flags([*others, answer(6, 250, 90)], lost, CFG) == []
    # usually uses the whole time: a long hold is nothing unusual for them
    slow = paper(95, 95, 95, 95, 95)
    assert rules.long_hold_correct_flags([*slow, answer(6, 600, 100)], [away(610, 20)], CFG) == []


def test_a_long_hold_with_focus_on_the_page_the_whole_time_is_not_flagged():
    others = paper(30, 30, 30, 30, 30)
    assert rules.long_hold_correct_flags([*others, answer(6, 200, 300)], [], CFG) == []
    # a loss during some other question does not count towards this one
    elsewhere = [away(20, 60)]
    assert rules.long_hold_correct_flags([*others, answer(6, 200, 300)], elsewhere, CFG) == []


def test_focus_must_have_been_lost_for_more_than_two_seconds():
    others = paper(30, 30, 30, 30, 30)
    held = [*others, answer(6, 200, 120)]
    assert rules.long_hold_correct_flags(held, [away(220, 2)], CFG) == []  # exactly 2 s
    assert len(rules.long_hold_correct_flags(held, [away(220, 2.5)], CFG)) == 1


def test_blinks_do_not_count_but_several_real_losses_add_up():
    others = paper(30, 30, 30, 30, 30)
    held = [*others, answer(6, 200, 120)]
    blinks = [away(210, 0.9), away(230, 0.9), away(250, 0.9)]  # 2.7 s, but none counts
    assert rules.long_hold_correct_flags(held, blinks, CFG) == []
    two_real = [away(210, 1.5), away(250, 1.5)]  # 3 s together
    assert len(rules.long_hold_correct_flags(held, two_real, CFG)) == 1


def test_only_the_part_of_a_loss_inside_the_question_counts():
    others = paper(30, 30, 30, 30, 30)
    held = [*others, answer(6, 200, 120)]  # open from 200 s to 320 s
    straddling = [away(319, 30)]  # only 1 s of it is inside the question
    assert rules.long_hold_correct_flags(held, straddling, CFG) == []
    assert len(rules.long_hold_correct_flags(held, [away(310, 30)], CFG)) == 1  # 10 s inside


def test_no_flag_with_fewer_than_five_other_answers_or_an_incorrect_one():
    four_others = paper(30, 30, 30, 30)
    lost = [away(160, 30)]
    assert rules.long_hold_correct_flags([*four_others, answer(5, 150, 300)], lost, CFG) == []
    five_others = paper(30, 30, 30, 30, 30)
    wrong = answer(6, 200, 300, correct=False)
    assert rules.long_hold_correct_flags([*five_others, wrong], [away(210, 30)], CFG) == []


# ----------------------------------------------------------------------- correct run after a gap


def run_paper():
    """Five ordinary 30 s answers (0 s to 154 s), then three quick ones of 8 s (155 s to 181 s).
    A gap that ends at 155 s therefore comes straight before the quick ones."""
    return paper(30, 30, 30, 30, 30, 8, 8, 8)


def test_three_quick_correct_in_a_row_after_a_five_second_loss():
    gap = rules.Span(at(150), at(155))  # exactly five seconds
    drafts = rules.correct_run_after_gap_flags(
        run_paper(), rules.run_gaps([gap], [], CFG), CFG
    )
    assert [d.kind for d in drafts] == ["CORRECT_RUN_AFTER_GAP"]
    assert drafts[0].weight == 2
    assert drafts[0].position == 6
    assert drafts[0].detail == {
        "gap_s": 5,
        "run_length": 3,
        "mean_s": 8.0,
        "own_median_s": 30,
    }


def test_a_run_at_the_candidates_normal_pace_is_not_flagged():
    gap = rules.run_gaps([rules.Span(at(150), at(155))], [], CFG)
    normal = paper(30, 30, 30, 30, 30, 30, 30, 30)  # the same shape, at their usual pace
    assert rules.correct_run_after_gap_flags(normal, gap, CFG) == []
    # the line is half their median: 15 s is not under it, 14 s is
    exactly = paper(30, 30, 30, 30, 30, 15, 15, 15)
    just_under = paper(30, 30, 30, 30, 30, 14, 14, 14)
    assert rules.correct_run_after_gap_flags(exactly, gap, CFG) == []
    assert len(rules.correct_run_after_gap_flags(just_under, gap, CFG)) == 1


def test_the_time_is_counted_from_the_end_of_the_gap_not_from_when_the_question_opened():
    # question 6 opened at 155 s but the candidate was away until 190 s, then answered at once
    answers = [
        *paper(30, 30, 30, 30, 30),
        answer(6, 155, 37),  # open 155 s to 192 s, 37 s in all
        answer(7, 193, 8),
        answer(8, 202, 8),
    ]
    gap = rules.run_gaps([rules.Span(at(160), at(190))], [], CFG)
    drafts = rules.correct_run_after_gap_flags(answers, gap, CFG)
    # 2 s after the gap for question 6, then 8 and 8: well under half of 30
    assert [d.position for d in drafts] == [6]
    assert drafts[0].detail["mean_s"] < 15


def test_no_flag_without_five_other_answers_to_compare_with():
    gap = rules.run_gaps([rules.Span(at(-1), at(5))], [], CFG)
    few = paper(8, 8, 8, 30, 30, 30, 30)  # four others after the three quick ones
    assert rules.correct_run_after_gap_flags(few, gap, CFG) == []
    enough = paper(8, 8, 8, 30, 30, 30, 30, 30)
    assert len(rules.correct_run_after_gap_flags(enough, gap, CFG)) == 1


def test_a_loss_just_under_five_seconds_is_not_a_gap():
    gap = rules.Span(at(5), at(9.9))
    assert rules.run_gaps([gap], [], CFG) == []


def test_a_blink_is_never_a_gap_whatever_the_gap_length_is_set_to():
    cfg = FlagConfig(run_gap_focus_s=0.5)  # even a gap threshold below the 1 s a loss must last
    assert rules.run_gaps([rules.Span(at(5), at(5.9))], [], cfg) == []


def test_a_wrong_answer_breaks_the_run_and_two_is_not_three():
    gap = rules.run_gaps([rules.Span(at(150), at(155))], [], CFG)
    broken = run_paper()
    broken[6] = answer(7, 164, 8, correct=False)  # the second quick answer is wrong: a run of 1
    assert rules.correct_run_after_gap_flags(broken, gap, CFG) == []
    two = paper(30, 30, 30, 30, 30, 30, 8, 8)
    gap_two = rules.run_gaps([rules.Span(at(180), at(185))], [], CFG)
    assert rules.correct_run_after_gap_flags(two, gap_two, CFG) == []


def test_idle_gaps_count_from_sixty_seconds():
    answers = paper(8, 8, 8, 30, 30, 30, 30, 30)
    exactly = [rules.Span(at(-61), at(-1))]  # 60 s, over before the first question opened
    under = [rules.Span(at(-60), at(-1))]  # 59 s
    assert len(rules.run_gaps([], exactly, CFG)) == 1
    assert rules.run_gaps([], under, CFG) == []
    gaps = rules.run_gaps([], exactly, CFG)
    assert len(rules.correct_run_after_gap_flags(answers, gaps, CFG)) == 1


def test_idle_end_carries_its_own_length():
    spans = rules.idle_spans([ev("idle_start", 100), ev("idle_end", 190, duration_s=90)])
    assert [(s.start, s.end) for s in spans] == [(at(100), at(190))]


# ----------------------------------------------------------------------------- fast run


def test_three_answers_in_a_row_under_twenty_seconds_are_one_flag():
    drafts = rules.fast_run_flags(paper(50, 19, 10, 19.9, 50), CFG)
    assert [d.kind for d in drafts] == ["FAST_RUN"]
    assert drafts[0].weight == 1
    assert drafts[0].position == 2
    assert drafts[0].ts == at(51)  # when question 2 opened
    assert drafts[0].detail == {"answers_in_a_row": 3, "answers_mean_s": 16.3}


def test_twenty_seconds_exactly_or_two_in_a_row_is_not_enough():
    assert rules.fast_run_flags(paper(19, 19, 20, 19), CFG) == []
    assert rules.fast_run_flags(paper(19, 19), CFG) == []


def test_a_long_run_is_one_flag_and_a_break_starts_a_new_one():
    drafts = rules.fast_run_flags(paper(5, 5, 5, 5, 5, 40, 5, 5, 5), CFG)
    assert [(d.position, d.detail["answers_in_a_row"]) for d in drafts] == [(1, 5), (7, 3)]


def test_right_or_wrong_makes_no_difference_to_a_fast_run():
    assert len(rules.fast_run_flags(paper(5, 5, 5, correct=False), CFG)) == 1


def test_a_skipped_or_unanswered_question_ends_a_run():
    items = paper(5, 5, 5, 5)
    skipped = [*items[:2], answer(3, 12, 5, skipped=True), *items[3:]]
    assert rules.fast_run_flags(skipped, CFG) == []
    open_ = rules.Answer(3, "Q003", None, at(12), None, None)
    assert rules.fast_run_flags([*items[:2], open_, *items[3:]], CFG) == []


# ------------------------------------------------------------------- hard, fast and correct


def test_a_hard_question_answered_correctly_in_under_fifteen_seconds_is_a_flag():
    answers = [answer(1, 0, 14.9, difficulty="hard"), answer(2, 20, 30, difficulty="hard")]
    (draft,) = rules.hard_fast_correct_flags(answers, CFG)
    assert draft.kind == "HARD_FAST_CORRECT" and draft.weight == 0.5 and draft.position == 1
    assert draft.ts == at(0) and draft.detail == {"time_s": 14.9}


def test_a_hard_answer_that_is_slow_wrong_skipped_or_not_hard_is_not_flagged():
    answers = [
        answer(1, 0, 15, difficulty="hard"),  # exactly 15 s
        answer(2, 20, 5, correct=False, difficulty="hard"),
        answer(3, 30, 5, difficulty="hard", skipped=True),
        answer(4, 40, 5, difficulty="medium"),
        answer(5, 50, 5),  # no difficulty at all, as on the Cytonn bank
    ]
    assert rules.hard_fast_correct_flags(answers, CFG) == []


# ------------------------------------------------------------------------------- flat pace


def levelled(easy, hard):
    """Easy answers of the given times, then hard ones, 1 s apart."""
    items, cursor = [], 0.0
    for position, (level, took) in enumerate(
        [("easy", t) for t in easy] + [("hard", t) for t in hard], start=1
    ):
        items.append(answer(position, cursor, took, difficulty=level))
        cursor += took + 1
    return items


def test_hard_questions_barely_slower_than_easy_ones_are_flagged_once():
    # easy median 20 s, hard median 23 s: under 1.2 x 20 = 24
    (draft,) = rules.flat_pace_flags(levelled([20, 20, 20], [22, 23, 25]), CFG)
    assert draft.kind == "FLAT_PACE" and draft.weight == 0.5 and draft.position is None
    assert draft.detail == {"easy_median_s": 20, "hard_median_s": 23}
    assert draft.ts == at(20 * 3 + 3 + 22 + 23 + 25 + 2)  # the end of the last hard answer
    # hard faster than easy is flat too
    assert len(rules.flat_pace_flags(levelled([20, 20, 20], [10, 10, 10]), CFG)) == 1


def test_a_normal_slowing_down_on_hard_questions_is_not_flagged():
    assert rules.flat_pace_flags(levelled([20, 20, 20], [24, 24, 24]), CFG) == []  # exactly 1.2 x
    assert rules.flat_pace_flags(levelled([20, 20, 20], [50, 50, 50]), CFG) == []


def test_flat_pace_needs_three_of_each_and_ignores_someone_slow_on_everything():
    assert rules.flat_pace_flags(levelled([20, 20, 20], [22, 22]), CFG) == []
    assert rules.flat_pace_flags(levelled([20, 20], [22, 22, 22]), CFG) == []
    assert rules.flat_pace_flags(levelled([40, 40, 40], [40, 40, 40]), CFG) == []  # not fast
    assert len(rules.flat_pace_flags(levelled([25, 25, 25], [29, 29, 29]), CFG)) == 1  # under 30 s
    assert rules.flat_pace_flags(paper(10, 10, 10, 10, 10, 10), CFG) == []  # no difficulty at all


def test_a_skipped_question_does_not_count_towards_flat_pace():
    items = levelled([20, 20, 20], [22, 22, 22])
    items[-1] = answer(6, 100, 22, difficulty="hard", skipped=True)
    assert rules.flat_pace_flags(items, CFG) == []  # only two hard answers left


# ------------------------------------------------------------------------ long, fast, correct


def test_a_long_question_answered_correctly_in_under_twenty_seconds_is_a_flag():
    answers = [answer(1, 0, 19.9, length=600), answer(2, 30, 19.9, length=2000)]
    drafts = rules.long_fast_correct_flags(answers, CFG)
    assert [d.kind for d in drafts] == ["LONG_FAST_CORRECT"] * 2
    assert drafts[0].weight == 0.5 and drafts[0].position == 1
    assert drafts[0].detail == {"time_s": 19.9, "question_chars": 600}


def test_a_short_slow_wrong_or_skipped_long_question_is_not_flagged():
    answers = [
        answer(1, 0, 10, length=599),  # one character short
        answer(2, 20, 20, length=900),  # exactly 20 s
        answer(3, 50, 5, correct=False, length=900),  # a guess
        answer(4, 60, 5, skipped=True, length=900),
        answer(5, 70, 5),  # length unknown
    ]
    assert rules.long_fast_correct_flags(answers, CFG) == []


# --------------------------------------------------------------------- heartbeats and the log


def beats(*seconds):
    return [at(s) for s in seconds]


def test_steady_heartbeats_leave_no_gap_and_thirty_five_seconds_is_still_fine():
    steady = beats(*range(10, 301, 10))
    assert rules.heartbeat_gaps(steady, at(0), at(300), CFG) == []
    edge = beats(10, 45, 55)  # a 35 s hole exactly
    assert rules.heartbeat_gaps(edge, at(0), at(55), CFG) == []


def test_a_longer_hole_is_a_gap_including_one_at_the_end():
    mid = beats(10, 20, 80, 90)
    assert [(g.start, g.end) for g in rules.heartbeat_gaps(mid, at(0), at(90), CFG)] == [
        (at(20), at(80))
    ]
    tail = beats(10, 20, 30)
    assert [(g.start, g.end) for g in rules.heartbeat_gaps(tail, at(0), at(120), CFG)] == [
        (at(30), at(120))
    ]


def test_a_session_with_no_heartbeats_at_all_is_not_judged():
    assert rules.heartbeat_gaps([], at(0), at(900), CFG) == []


def test_an_unexplained_gap_is_a_logging_problem_with_no_weight():
    gap = [rules.Span(at(100), at(160))]
    drafts = rules.logging_problem_flags(gap, [], [], CFG)
    assert [d.kind for d in drafts] == ["LOGGING_PROBLEM"]
    assert drafts[0].weight == 0
    assert drafts[0].detail == {"heartbeat_gap_s": 60}


def test_a_dropped_connection_or_a_reload_explains_a_gap():
    gap = [rules.Span(at(100), at(160))]
    drop = [rules.Span(at(95), at(140))]
    assert rules.logging_problem_flags(gap, drop, [], CFG) == []
    assert rules.logging_problem_flags(gap, [], [ev("reload", 130)], CFG) == []
    assert rules.logging_problem_flags(gap, [], [ev("page_load", 101)], CFG) == []
    elsewhere = [ev("reload", 400)]
    assert len(rules.logging_problem_flags(gap, [], elsewhere, CFG)) == 1


# --------------------------------------------------------------------------------- the cohort


def member(key, mean, spread):
    return rules.CohortMember(key, mean, spread, at(0))


def test_the_cohort_rules_wait_for_eight_candidates():
    seven = [member(f"s{i}", 40 + i, 10 + i) for i in range(6)] + [member("odd", 5, 1)]
    assert rules.cohort_flags(seven, CFG) == {}


def test_an_outlier_among_eight_or_more_is_flagged_in_the_right_direction():
    group = [member(f"s{i}", 40 + (i % 4), 10 + (i % 3)) for i in range(10)]
    group.append(member("fast", 12, 2))
    out = rules.cohort_flags(group, CFG)
    assert set(out) == {"fast"}
    kinds = {d.kind: d.detail["direction"] for d in out["fast"]}
    assert kinds == {"PACE_OUTLIER": "fast", "SPREAD_OUTLIER": "narrow"}
    assert all(d.weight == 1.5 for d in out["fast"])


def test_a_group_with_no_spread_flags_nobody():
    same = [member(f"s{i}", 40, 10) for i in range(10)]
    assert rules.cohort_flags(same, CFG) == {}
    assert rules.robust_z([40.0] * 5, 40.0) is None


def test_baseline_is_the_median_and_the_raw_median_absolute_deviation():
    assert rules.baseline([10, 12, 14, 16, 18]) == (14, 2)
    assert rules.baseline([5.0, 5.0, 5.0]) == (5.0, 0.0)


def test_percentile_is_the_share_at_or_below():
    values = [10.0, 20.0, 30.0, 40.0]
    assert rules.percentile_of(values, 10) == 25
    assert rules.percentile_of(values, 40) == 100
    assert rules.percentile_of([], 5) == 0


# ---------------------------------------------------------------------------------- the score


def flag(label, kind, weight, at_s):
    return ScoredFlag(label, kind, weight, at_s)


def test_the_score_adds_weights_extra_kinds_and_flags_close_together():
    total, lines = score_flags(
        [
            flag("F1", "COPY_ATTEMPT", 3, 100),
            flag("F2", "FOCUS_LOSS", 0.5, 150),  # within 120 s of F1
            flag("F3", "LONG_HOLD_CORRECT", 3, 900),
        ],
        CFG,
    )
    # 3 + 0.5 + 3, two extra kinds (+2), two flags within 120 s (+1)
    assert total == 9.5
    labels = [ln.label for ln in lines]
    assert "COPY_ATTEMPT (F1)" in labels
    assert any(label.startswith("Extra distinct kinds") for label in labels)
    assert any(label.startswith("Two flags within") for label in labels)


def test_focus_loss_points_stop_at_the_cap_but_every_loss_still_shows():
    flags = [flag(f"F{i}", "FOCUS_LOSS", 0.5, i * 500) for i in range(1, 7)]
    total, lines = score_flags(flags, CFG)
    assert total == 2.0
    assert len(lines) == 6
    assert [ln.points for ln in lines] == [0.5, 0.5, 0.5, 0.5, 0.0, 0.0]


def test_a_gap_in_the_record_scores_nothing_and_adds_no_extras():
    total, lines = score_flags([flag("F1", "LOGGING_PROBLEM", 0, 300)], CFG)
    assert total == 0
    assert [ln.points for ln in lines] == [0]
    mixed, _ = score_flags(
        [flag("F1", "LOGGING_PROBLEM", 0, 300), flag("F2", "COPY_ATTEMPT", 3, 310)], CFG
    )
    assert mixed == 3  # no extra-kind point for the logging problem, nor a "close together" one
    assert is_logging_only(["LOGGING_PROBLEM"]) is True
    assert is_logging_only(["LOGGING_PROBLEM", "COPY_ATTEMPT"]) is False
    assert is_logging_only([]) is False


def test_every_event_the_candidate_is_warned_about_is_one_a_rule_reads():
    """The test screen's notice is driven by WARN_EVENT_TYPES. If a rule stopped reading one of them
    (or a name were changed in only one place) the candidate would be told about something that no
    longer raises a flag, so each type has to produce a flag on its own."""
    paper_ = paper(20, 20)
    for kind in sorted(rules.WARN_EVENT_TYPES):
        events = [rules.Ev(kind, at(5), {"combo": "PrintScreen"})]
        if kind == rules.FOCUS_EVENT:  # a loss counts once it has lasted long enough
            events.append(rules.Ev(rules.FOCUS_RETURN_EVENT, at(5 + CFG.focus_loss_min_s + 5)))
        drafts = (
            rules.focus_loss_flags(rules.focus_losses(events, at(40)), paper_, CFG)
            + rules.copy_attempt_flags(events, paper_, CFG)
            + rules.screenshot_key_flags(events, paper_, CFG)
        )
        assert drafts, f"no rule reads {kind}"
