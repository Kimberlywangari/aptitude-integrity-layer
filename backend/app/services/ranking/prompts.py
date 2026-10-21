"""What the model is told. Kept in one place so the wording that keeps it to ranking and
explaining (and out of verdicts) can be read, tested and changed without touching a provider.

The system prompt is the benchmark's second version (eval/metrics/ai_benchmark.py), which was
written after the first one let verdict words and guesses through on small local models.
"""

import json
from typing import Any

from app.services.ranking.base import Assessment

SYSTEM_PROMPT = (
    "You are helping a human reviewer. You only rank and explain. You never give a verdict "
    "and never recommend rejecting or disqualifying anyone.\n"
    "Never use the words cheat, cheating, cheated, guilty, dishonest, fraud, misconduct, "
    "disqualify or reject, not even to deny them. Describe behaviour instead, for example "
    "'a copy attempt on Q11' or 'a 212 s hold on Q22'.\n"
    "Say only what the flags show. Do not guess at reasons or methods (no 'answer key', "
    "'external material', 'automated' or similar). Use only numbers that appear in the "
    "packet, and use each number for what it is: score is a score, not a count of "
    "questions.\n"
    "Cite flag IDs (F1, F2, ...) and innocent signal IDs (I1, M1, ...). If the packet has an "
    "innocent signal that could explain the flags, say so and set innocent_explanation.\n"
    "Strength scale: 5 = several different kinds of flag close together in time with nothing "
    "innocent explaining them; 4 = several flags that support each other, little innocent "
    "explanation; 3 = two flags, or flags that are far apart or partly explained; 2 = one "
    "flag, or flags that an innocent signal explains; 1 = nothing beyond routine context. "
    "A cohort-only outlier (PACE_OUTLIER or SPREAD_OUTLIER on its own) is context and is "
    "never above 2. A high score or a fast pace is not evidence on its own.\n"
    "Answer with the JSON schema only; explanation at most 80 words."
)

# About 1,500 tokens of packet; past this, the least useful detail is dropped first.
MAX_PACKET_CHARS = 6000
KEEP_FOCUS_DETAIL = 3


def schema() -> dict[str, Any]:
    return Assessment.model_json_schema()


def compact(packet: dict[str, Any], max_chars: int = MAX_PACKET_CHARS) -> dict[str, Any]:
    """The packet as the model sees it. When it is long, the context a reviewer weighs for
    themselves goes first (pre-check and full-screen exits), then the detail of repeated focus
    losses beyond the first few. Flag ids, the `facts` block and every other flag are untouched,
    so whatever the model cites can still be checked."""
    if len(json.dumps(packet)) <= max_chars:
        return packet
    smaller = {k: v for k, v in packet.items() if k not in ("precheck", "fullscreen_exits")}
    if len(json.dumps(smaller)) <= max_chars:
        return smaller
    seen = 0
    flags = []
    for flag in smaller["flags"]:
        if flag["kind"] == "FOCUS_LOSS":
            seen += 1
            if seen > KEEP_FOCUS_DETAIL:
                flag = {**flag, "detail": {}}
        flags.append(flag)
    return {**smaller, "flags": flags}


def build_messages(
    packet: dict[str, Any], violations: list[str] | None = None
) -> list[dict[str, str]]:
    packet_text = json.dumps(compact(packet))
    user = f"Evidence packet:\n{packet_text}\n\nSchema:\n{json.dumps(schema())}"
    if violations:
        user += (
            "\n\nYour previous answer contained claims that are not in the packet. "
            "Answer again using only facts that are in the packet. Problems found:\n- "
            + "\n- ".join(violations)
        )
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user},
    ]
