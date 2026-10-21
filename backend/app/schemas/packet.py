"""The evidence packet (master plan 7.5): everything a reviewer, and the AI, are shown about one
flagged candidate. Candidate ID only; nothing in it is a name, a token, a device label or free
text the candidate wrote.

The shape matches eval/fixtures/synthetic_packets.py, so the benchmark's hand-built packets and
real ones are interchangeable.
"""

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


class PacketFlag(BaseModel):
    id: str  # F1, F2 ... in time order, the same names the reviewer sees
    kind: str
    server_ts: datetime
    elapsed_s: int
    question_number: int | None
    detail: dict[str, Any]


class PacketQuestion(BaseModel):
    number: int
    section: str
    difficulty: str | None


class Facts(BaseModel):
    """Every question number, whole-second time and count the packet contains. The AI is told to
    use only these, and the fact checker rejects an explanation that cites anything else."""

    question_numbers: list[int]
    times_s: list[int]
    counts: dict[str, int]


class Packet(BaseModel):
    candidate_id: str
    flags: list[PacketFlag] = Field(min_length=1)
    questions: list[PacketQuestion]
    # percentiles against the sitting, or {"cohort_skipped": "too_small"}
    vs_sitting: dict[str, Any]
    score: int  # correct answers: context, never a flag
    pace_s_per_q: int  # context, never a flag
    history_source: Literal["cytonn", "synthetic"]
    # context only: leaving full screen is something a page cannot stop and an honest candidate
    # can do by accident
    fullscreen_exits: list[dict[str, int]]
    precheck: dict[str, Any]
    innocent_signals: list[dict[str, Any]]
    mic_silence: list[dict[str, Any]]
    video_anchor: str | None  # server time recording began, for flag-to-video offsets
    facts: Facts
