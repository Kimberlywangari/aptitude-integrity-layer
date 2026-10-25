"""Every threshold and weight for the rule flags, in one place (master plan 7.4).

These are the proposed defaults. They are tuned on the honest cohort, never on the cheaters alone,
and changing one here changes every flag and score the next time flags are computed.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class FlagConfig:
    # FOCUS_LOSS: each loss of at least this long. A shorter one is ignored by every rule. The
    # points of all of a candidate's losses together never go past the cap, however many there are.
    focus_loss_min_s: float = 1.0
    focus_loss_weight: float = 0.5
    focus_loss_cap: float = 2.0

    # COPY_ATTEMPT: any copy or cut attempt on question text.
    copy_weight: float = 3.0

    # SCREENSHOT_KEY: a screenshot key combination pressed. One flag per press. The page cannot see
    # the screenshot, only the keys, so this is a prompt for a reviewer to look, nothing more.
    # Unlike the focus-loss cap above, nothing limits how many of these add up.
    screenshot_weight: float = 2.0

    # LONG_HOLD_CORRECT: slower than max(factor x own median, own median + extra), answered
    # correctly, own median taken from at least this many other answers, and only when focus was
    # lost for more than `hold_min_focus_lost_s` in total while that question was open. (This used
    # to score 3, plus 1 more for a focus loss; a loss is now required, so the weight is 4.)
    hold_min_other_answers: int = 5
    hold_factor: float = 3.0
    hold_extra_s: float = 45.0
    hold_min_focus_lost_s: float = 2.0
    hold_weight: float = 4.0
    # A question closes after 105 s, so the line never goes above this; without it a candidate
    # whose usual time is 35 s or more could never be flagged.
    hold_cap_s: float = 90.0

    # CORRECT_RUN_AFTER_GAP: this many correct answers straight after a focus loss or idle gap, and
    # only when they were quick: the average time per question counted from the end of the gap is
    # under `run_fast_factor` x the candidate's own median on their other answers (at least
    # `run_min_other_answers` of them, or there is nothing fair to compare against).
    run_gap_focus_s: float = 5.0
    run_gap_idle_s: float = 60.0
    run_length: int = 3
    run_fast_factor: float = 0.5
    run_min_other_answers: int = 5
    run_weight: float = 2.0

    # LOGGING_PROBLEM: no heartbeat for longer than this, unexplained.
    heartbeat_gap_s: float = 35.0

    # PACE_OUTLIER / SPREAD_OUTLIER: robust z across a closed sitting of enough candidates.
    cohort_min_candidates: int = 8
    cohort_z: float = 3.0
    pace_weight: float = 1.5
    spread_weight: float = 1.5

    # Who enters the queue: a rule score at or above this, or any LOGGING_PROBLEM (master plan
    # A10). A lone loss of focus (0.5) is not enough on its own.
    flagged_score: float = 1.0

    # Rule score extras.
    extra_kind_points: float = 1.0
    near_flags_window_s: float = 120.0
    near_flags_points: float = 1.0

    # A muted or silent stretch is only shown to a reviewer from this length (context, no flag).
    mic_silence_min_s: float = 60.0


DEFAULTS = FlagConfig()
