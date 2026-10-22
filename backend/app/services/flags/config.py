"""Every threshold and weight for the rule flags, in one place (master plan 7.4).

These are the proposed defaults. They are tuned on the honest cohort, never on the cheaters alone,
and changing one here changes every flag and score the next time flags are computed.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class FlagConfig:
    # FOCUS_LOSS: each loss of at least this long, with the running total capped.
    focus_loss_min_s: float = 1.0
    focus_loss_weight: float = 0.5
    focus_loss_cap: float = 2.0

    # COPY_ATTEMPT: any copy or cut attempt on question text.
    copy_weight: float = 3.0

    # LONG_HOLD_CORRECT: slower than max(factor x own median, own median + extra), answered
    # correctly, own median taken from at least this many other answers.
    hold_min_other_answers: int = 5
    hold_factor: float = 3.0
    hold_extra_s: float = 45.0
    hold_weight: float = 3.0
    hold_focus_bonus: float = 1.0

    # CORRECT_RUN_AFTER_GAP: this many correct answers straight after a focus loss or idle gap.
    run_gap_focus_s: float = 5.0
    run_gap_idle_s: float = 60.0
    run_length: int = 3
    run_weight: float = 2.0

    # LOGGING_PROBLEM: no heartbeat for longer than this, unexplained.
    heartbeat_gap_s: float = 35.0

    # FAST_CORRECT_VS_HISTORY: correct and faster than factor x the question's p25; hard
    # questions use the larger factor because a quick correct answer there says more.
    fast_p25_factor: float = 0.5
    fast_hard_multiplier: float = 1.5
    fast_min_questions: int = 2
    fast_weight: float = 2.0
    # A question's history counts only when it comes from at least this many past candidates.
    fast_min_history_n: int = 30

    # PACE_OUTLIER / SPREAD_OUTLIER: robust z across a closed sitting of enough candidates.
    cohort_min_candidates: int = 8
    cohort_z: float = 3.0
    pace_weight: float = 1.5
    spread_weight: float = 1.5

    # Who enters the queue: a rule score at or above this, or any LOGGING_PROBLEM (master plan
    # A10, to be confirmed with Cytonn). A lone loss of focus (0.5) is not enough on its own.
    flagged_score: float = 1.0

    # Rule score extras.
    extra_kind_points: float = 1.0
    near_flags_window_s: float = 120.0
    near_flags_points: float = 1.0

    # A muted or silent stretch is only shown to a reviewer from this length (context, no flag).
    mic_silence_min_s: float = 60.0


DEFAULTS = FlagConfig()
