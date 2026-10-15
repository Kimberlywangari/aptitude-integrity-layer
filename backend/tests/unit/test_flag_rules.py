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


def answer(position, opened, took, correct=True, difficulty=None, p25=None, skipped=False):
    return rules.Answer(
        position=position,
        question_id=f"Q{position:03d}",
        difficulty=difficulty,
        opened_at=at(opened),
        answered_at=at(opened + took),
        correct=correct,
        skipped=skipped,
        p25_s=p25,
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


# ---------------------------------------------------------------------------- long hold, correct


def test_long_hold_fires_above_the_limit_and_not_at_it():
    # five others at 30 s: the limit is max(3 x 30, 30 + 45) = 90 s
    others = paper(30, 30, 30, 30, 30)
    just_over = [*others, answer(6, 200, 91)]
    exactly = [*others, answer(6, 200, 90)]

    fired = rules.long_hold_correct_flags(just_over, [], CFG)
    assert [d.kind for d in fired] == ["LONG_HOLD_CORRECT"]
    assert fired[0].weight == 3
    assert fired[0].position == 6
    assert fired[0].detail == {"time_s": 91, "own_median_s": 30, "focus_lost_during": False}
    assert rules.long_hold_correct_flags(exactly, [], CFG) == []


def test_the_extra_45_seconds_wins_when_the_median_is_small():
    # median 10 s: 3 x 10 = 30 but 10 + 45 = 55, so 55 s is the limit
    others = paper(10, 10, 10, 10, 10)
    assert rules.long_hold_correct_flags([*others, answer(6, 100, 55)], [], CFG) == []
    assert len(rules.long_hold_correct_flags([*others, answer(6, 100, 56)], [], CFG)) == 1


def test_a_focus_loss_during_the_hold_adds_a_point():
    others = paper(30, 30, 30, 30, 30)
    held = answer(6, 200, 120)
    loss = rules.Span(at(220), at(250))
    drafts = rules.long_hold_correct_flags([*others, held], [loss], CFG)
    assert drafts[0].weight == 4
    assert drafts[0].detail["focus_lost_during"] is True


def test_no_flag_with_fewer_than_five_other_answers_or_an_incorrect_one():
    four_others = paper(30, 30, 30, 30)
    assert rules.long_hold_correct_flags([*four_others, answer(5, 150, 300)], [], CFG) == []
    five_others = paper(30, 30, 30, 30, 30)
    wrong = answer(6, 200, 300, correct=False)
    assert rules.long_hold_correct_flags([*five_others, wrong], [], CFG) == []


# ----------------------------------------------------------------------- correct run after a gap


def test_three_correct_in_a_row_after_a_five_second_loss():
    answers = paper(30, 30, 30, 30)
    gap = rules.Span(at(5), at(10))  # exactly five seconds
    drafts = rules.correct_run_after_gap_flags(answers, rules.run_gaps([gap], [], CFG), CFG)
    assert [d.kind for d in drafts] == ["CORRECT_RUN_AFTER_GAP"]
    assert drafts[0].weight == 2
    assert drafts[0].detail == {"gap_s": 5, "run_length": 4}


def test_a_loss_just_under_five_seconds_is_not_a_gap():
    gap = rules.Span(at(5), at(9.9))
    assert rules.run_gaps([gap], [], CFG) == []


def test_a_wrong_answer_breaks_the_run_and_two_is_not_three():
    gap = rules.run_gaps([rules.Span(at(1), at(20))], [], CFG)
    broken = paper(30, 30, 30, 30)
    broken[2] = answer(3, 62, 30, correct=False)
    assert rules.correct_run_after_gap_flags(broken, gap, CFG) == []  # run is 2
    two = paper(30, 30)
    assert rules.correct_run_after_gap_flags(two, gap, CFG) == []


def test_idle_gaps_count_from_sixty_seconds():
    answers = paper(30, 30, 30)  # answered at 30 s, 61 s and 92 s
    exactly = [rules.Span(at(-50), at(10))]  # 60 s, over before the first answer
    under = [rules.Span(at(-49), at(10))]  # 59 s
    assert len(rules.run_gaps([], exactly, CFG)) == 1
    assert rules.run_gaps([], under, CFG) == []
    gaps = rules.run_gaps([], exactly, CFG)
    assert len(rules.correct_run_after_gap_flags(answers, gaps, CFG)) == 1


def test_idle_end_carries_its_own_length():
    spans = rules.idle_spans([ev("idle_start", 100), ev("idle_end", 190, duration_s=90)])
    assert [(s.start, s.end) for s in spans] == [(at(100), at(190))]


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


# --------------------------------------------------------------------------- fast and correct


def test_two_correct_answers_under_half_the_p25_make_one_flag():
    answers = [
        answer(1, 0, 9, p25=40),  # 9 < 20
        answer(2, 10, 19.9, p25=40),  # just under 20
        answer(3, 40, 20, p25=40),  # exactly 20: not under
    ]
    drafts = rules.fast_correct_flags(answers, CFG)
    assert [d.kind for d in drafts] == ["FAST_CORRECT_VS_HISTORY"]
    assert drafts[0].weight == 2
    assert drafts[0].detail["questions"] == [1, 2]


def test_one_quick_answer_is_not_enough_and_a_wrong_one_does_not_count():
    assert rules.fast_correct_flags([answer(1, 0, 5, p25=40)], CFG) == []
    wrong = [answer(1, 0, 5, p25=40), answer(2, 10, 5, p25=40, correct=False)]
    assert rules.fast_correct_flags(wrong, CFG) == []


def test_hard_questions_use_the_wider_threshold():
    # 28 s is over 0.5 x 40 = 20 but under 0.75 x 40 = 30
    easy = [answer(1, 0, 28, p25=40), answer(2, 30, 28, p25=40)]
    hard = [
        answer(1, 0, 28, p25=40, difficulty="hard"),
        answer(2, 30, 28, p25=40, difficulty="hard"),
    ]
    assert rules.fast_correct_flags(easy, CFG) == []
    assert len(rules.fast_correct_flags(hard, CFG)) == 1


def test_questions_with_no_history_are_ignored():
    assert rules.fast_correct_flags([answer(1, 0, 1), answer(2, 5, 1)], CFG) == []


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
