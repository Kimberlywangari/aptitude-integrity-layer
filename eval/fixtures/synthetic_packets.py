"""Hand-built evidence packets with a known expected strength band, for model benchmarks.

Stand-ins until the simulator (D5 to D10) can produce real packets. The shape follows master plan
section 7.5 and uses the candidate ID only, never a name. Each entry has a `band`:

- strong: several different kinds of flag, close together, nothing innocent that explains them
- medium: a couple of flags, far apart or partly explained
- weak: a lone flag, or a cohort-only outlier, or an innocent signal that explains it
"""

from datetime import UTC, datetime, timedelta
from typing import Any

Packet = dict[str, Any]

_START = datetime(2026, 10, 28, 9, 0, 0, tzinfo=UTC)


def _ts(elapsed_s: int) -> str:
    return (_START + timedelta(seconds=elapsed_s)).strftime("%Y-%m-%dT%H:%M:%SZ")


def _flag(fid: str, kind: str, elapsed_s: int, question_number: int | None = None, **detail: Any):
    return {
        "id": fid,
        "kind": kind,
        "server_ts": _ts(elapsed_s),
        "elapsed_s": elapsed_s,
        "question_number": question_number,
        "detail": detail,
    }


def _ints(value: Any) -> list[int]:
    if isinstance(value, bool):
        return []
    if isinstance(value, int):
        return [value]
    if isinstance(value, dict):
        return [n for v in value.values() for n in _ints(v)]
    if isinstance(value, list):
        return [n for v in value for n in _ints(v)]
    return []


def _facts(packet: Packet) -> dict[str, Any]:
    questions = {q["number"] for q in packet["questions"]}
    times: set[int] = {packet["pace_s_per_q"]}
    for flag in packet["flags"]:
        if flag["question_number"] is not None:
            questions.add(flag["question_number"])
        questions.update(flag["detail"].get("questions", []))
        times.add(flag["elapsed_s"])
        times.update(_ints({k: v for k, v in flag["detail"].items() if k != "questions"}))
    times.update(_ints(packet["innocent_signals"]))
    times.update(_ints(packet["mic_silence"]))
    counts = {
        "flags": len(packet["flags"]),
        "innocent_signals": len(packet["innocent_signals"]),
        "mic_silence": len(packet["mic_silence"]),
        "score": packet["score"],
    }
    counts.update(packet["vs_sitting"] if "cohort_skipped" not in packet["vs_sitting"] else {})
    return {"question_numbers": sorted(questions), "times_s": sorted(times), "counts": counts}


def _packet(
    cid: str,
    flags: list[dict[str, Any]],
    questions: list[tuple[int, str, str | None]],
    *,
    score: int,
    pace: int,
    vs_sitting: dict[str, Any] | None = None,
    innocent: list[dict[str, Any]] | None = None,
    mic: list[dict[str, Any]] | None = None,
) -> Packet:
    packet: Packet = {
        "candidate_id": cid,
        "flags": flags,
        "questions": [
            {"number": n, "section": section, "difficulty": difficulty}
            for n, section, difficulty in questions
        ],
        "vs_sitting": vs_sitting or {"cohort_skipped": "too_small"},
        "score": score,
        "pace_s_per_q": pace,
        "innocent_signals": innocent or [],
        "mic_silence": mic or [],
        "video_anchor": _ts(0),
    }
    packet["facts"] = _facts(packet)
    return packet


_COHORT = {"pace_percentile": 8, "spread_percentile": 3, "score_percentile": 91}

PACKETS: list[dict[str, Any]] = [
    {
        "id": "S1",
        "band": "strong",
        "packet": _packet(
            "C-0101",
            [
                _flag("F1", "COPY_ATTEMPT", 310, 9, target="question_text", length=212),
                _flag(
                    "F2",
                    "LONG_HOLD_CORRECT",
                    1125,
                    22,
                    time_s=212,
                    own_median_s=38,
                    focus_lost_during=True,
                ),
                _flag(
                    "F3",
                    "CORRECT_RUN_AFTER_GAP",
                    1410,
                    23,
                    gap_s=74,
                    run_length=3,
                    questions=[23, 24, 25],
                    times_s=[9, 8, 11],
                ),
                _flag(
                    "F4",
                    "FAST_CORRECT_VS_HISTORY",
                    1852,
                    30,
                    questions=[30, 31],
                    times_s=[7, 6],
                    p25_s=[41, 38],
                    history_source="cytonn",
                ),
            ],
            [
                (9, "Numerical", "hard"),
                (22, "Logical", "medium"),
                (23, "Verbal", "easy"),
                (24, "Verbal", "medium"),
                (25, "Verbal", "medium"),
                (30, "Numerical", "hard"),
                (31, "Numerical", "hard"),
            ],
            score=34,
            pace=21,
            vs_sitting=_COHORT,
            mic=[
                {
                    "id": "M1",
                    "start_s": 1180,
                    "end_s": 1255,
                    "duration_s": 75,
                    "layers": ["browser", "server"],
                }
            ],
        ),
    },
    {
        "id": "S2",
        "band": "strong",
        "packet": _packet(
            "C-0102",
            [
                _flag("F1", "COPY_ATTEMPT", 140, 4, target="question_text", length=96),
                _flag("F2", "FOCUS_LOSS_CORRECT", 158, 5, focus_lost_s=44, answered_correct=True),
                _flag(
                    "F3",
                    "LONG_HOLD_CORRECT",
                    700,
                    12,
                    time_s=180,
                    own_median_s=30,
                    focus_lost_during=True,
                ),
                _flag(
                    "F4",
                    "CORRECT_RUN_AFTER_GAP",
                    905,
                    13,
                    gap_s=88,
                    run_length=4,
                    questions=[13, 14, 15, 16],
                    times_s=[6, 7, 5, 8],
                ),
            ],
            [
                (4, "Numerical", "medium"),
                (5, "Numerical", "hard"),
                (12, "Logical", "hard"),
                (13, "Verbal", "medium"),
                (14, "Verbal", "medium"),
                (15, "Verbal", "hard"),
                (16, "Verbal", "medium"),
            ],
            score=29,
            pace=19,
            vs_sitting={"pace_percentile": 12, "spread_percentile": 20, "score_percentile": 84},
            innocent=[{"id": "I1", "kind": "connection_lost", "elapsed_s": 400, "duration_s": 9}],
        ),
    },
    {
        "id": "S3",
        "band": "strong",
        "packet": _packet(
            "C-0103",
            [
                _flag(
                    "F1",
                    "FAST_CORRECT_VS_HISTORY",
                    1000,
                    18,
                    questions=[18, 19, 27],
                    times_s=[5, 6, 4],
                    p25_s=[44, 39, 52],
                    history_source="cytonn",
                ),
                _flag(
                    "F2",
                    "CORRECT_RUN_AFTER_GAP",
                    1210,
                    20,
                    gap_s=95,
                    run_length=3,
                    questions=[20, 21, 22],
                    times_s=[8, 7, 9],
                ),
                _flag(
                    "F3",
                    "SPREAD_OUTLIER",
                    2400,
                    None,
                    robust_z=-3.8,
                    note="answer times in a narrow band",
                ),
                _flag("F4", "PACE_OUTLIER", 2400, None, robust_z=-3.2, mean_s_per_q=14),
            ],
            [
                (18, "Logical", "hard"),
                (19, "Logical", "hard"),
                (20, "Verbal", "medium"),
                (21, "Verbal", "hard"),
                (22, "Verbal", "medium"),
                (27, "Numerical", "hard"),
            ],
            score=31,
            pace=14,
            vs_sitting={"pace_percentile": 2, "spread_percentile": 1, "score_percentile": 88},
        ),
    },
    {
        "id": "M1",
        "band": "medium",
        "packet": _packet(
            "C-0201",
            [
                _flag("F1", "COPY_ATTEMPT", 520, 11, target="question_text", length=140),
                _flag("F2", "FOCUS_LOSS_CORRECT", 1700, 29, focus_lost_s=22, answered_correct=True),
            ],
            [(11, "Logical", "medium"), (29, "Numerical", "medium")],
            score=22,
            pace=38,
            vs_sitting={"pace_percentile": 48, "spread_percentile": 55, "score_percentile": 52},
        ),
    },
    {
        "id": "M2",
        "band": "medium",
        "packet": _packet(
            "C-0202",
            [
                _flag(
                    "F1",
                    "LONG_HOLD_CORRECT",
                    400,
                    8,
                    time_s=130,
                    own_median_s=40,
                    focus_lost_during=False,
                ),
                _flag(
                    "F2",
                    "CORRECT_RUN_AFTER_GAP",
                    900,
                    9,
                    gap_s=61,
                    run_length=3,
                    questions=[9, 10, 11],
                    times_s=[15, 18, 14],
                ),
            ],
            [
                (8, "Numerical", "hard"),
                (9, "Verbal", "medium"),
                (10, "Verbal", "easy"),
                (11, "Verbal", "medium"),
            ],
            score=25,
            pace=33,
            innocent=[
                {
                    "id": "I1",
                    "kind": "self_report",
                    "category": "technical_issue",
                    "note": "screen froze once",
                }
            ],
        ),
    },
    {
        "id": "W1",
        "band": "weak",
        "packet": _packet(
            "C-0301",
            [_flag("F1", "FOCUS_LOSS_CORRECT", 900, 14, focus_lost_s=8, answered_correct=True)],
            [(14, "Logical", "medium")],
            score=18,
            pace=44,
            vs_sitting={"pace_percentile": 60, "spread_percentile": 50, "score_percentile": 40},
            innocent=[
                {"id": "I1", "kind": "connection_lost", "elapsed_s": 892, "duration_s": 20},
                {"id": "I2", "kind": "page_load", "elapsed_s": 893},
            ],
        ),
    },
    {
        "id": "W2",
        "band": "weak",
        "packet": _packet(
            "C-0302",
            [_flag("F1", "PACE_OUTLIER", 2500, None, robust_z=-3.1, mean_s_per_q=17)],
            [],
            score=38,
            pace=17,
            vs_sitting={"pace_percentile": 5, "spread_percentile": 40, "score_percentile": 96},
        ),
    },
    {
        "id": "W3",
        "band": "weak",
        "packet": _packet(
            "C-0303",
            [
                _flag(
                    "F1",
                    "SPREAD_OUTLIER",
                    2500,
                    None,
                    robust_z=-3.3,
                    note="answer times in a narrow band",
                )
            ],
            [],
            score=36,
            pace=28,
            vs_sitting={"pace_percentile": 35, "spread_percentile": 4, "score_percentile": 90},
        ),
    },
    {
        "id": "W4",
        "band": "weak",
        "packet": _packet(
            "C-0304",
            [
                _flag(
                    "F1",
                    "LONG_HOLD_CORRECT",
                    300,
                    6,
                    time_s=95,
                    own_median_s=30,
                    focus_lost_during=False,
                )
            ],
            [(6, "Verbal", "medium")],
            score=20,
            pace=41,
            innocent=[
                {
                    "id": "I1",
                    "kind": "self_report",
                    "category": "interruption",
                    "note": "someone knocked at the door",
                }
            ],
        ),
    },
    {
        "id": "W5",
        "band": "weak",
        "packet": _packet(
            "C-0305",
            [
                _flag("F1", "FOCUS_LOSS_CORRECT", 200, 3, focus_lost_s=6, answered_correct=True),
                _flag("F2", "FOCUS_LOSS_CORRECT", 1100, 20, focus_lost_s=7, answered_correct=True),
            ],
            [(3, "Numerical", "easy"), (20, "Logical", "medium")],
            score=19,
            pace=46,
            vs_sitting={"pace_percentile": 62, "spread_percentile": 58, "score_percentile": 45},
            innocent=[{"id": "I1", "kind": "page_load", "elapsed_s": 198}],
        ),
    },
]
