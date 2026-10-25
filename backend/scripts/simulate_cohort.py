"""A made-up sitting, so the reviewer screens have something real to read before real data exists.

    python -m scripts.jobs simulate_cohort [--seed 1] [--name NAME] [--purge]

It writes a closed sitting of sixteen finished sessions straight into the database: answers with
believable times, the action log, heartbeats, and a few technical problems and complaints. Then
it runs the real flag rules over them, so the queue the reviewer sees is produced by the same code
that will read Cytonn's sittings.

Everything it makes is recognisable and removable:
- the sitting name starts with "Simulated", and its candidates are `sim-001`, `sim-002` ...
- `--purge` deletes the sitting, the sessions and everything attached, and nothing else.
- it never touches the invited candidates or the sitting a person is actually sitting in.

The cheating cases are scripted so the rules have something to find (a tab lookup, a copier, an
answer runner, a gap in the log). The honest cases include people who are quick, and people with a
dropped connection or a camera fault, because a rule that cannot tell those apart from the
scripted cases is not worth using.

Nothing here uses past candidates' statistics: how long a question takes and how likely it is to be
answered correctly come from its difficulty alone, so it works on any bank, including one with no
history at all.
"""

import argparse
import hashlib
import math
import random
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.core.security import hash_token
from app.models import (
    AuditLog,
    Candidate,
    Complaint,
    Event,
    Heartbeat,
    Option,
    Question,
    SessionQuestion,
    Sitting,
    TestSession,
)
from app.services.flags.config import DEFAULTS
from app.services.flags.engine import FlagRun, compute_sitting_flags

SITTING_NAME = "Simulated cohort 1 (made up)"
SIM_PREFIX = "sim"  # candidates are `sim-001` ...; another prefix keeps a second cohort apart
DEFAULT_START = datetime(2026, 10, 14, 9, 0, tzinfo=UTC)
QUESTION_COUNT = 12
DURATION_S = 1800
PER_SECTION = 4

# How long a question of each difficulty usually takes, and how often a middling candidate gets it
# right. A stand-in for a person's behaviour, not a measurement of one.
TYPICAL = {"easy": (22.0, 0.85), "medium": (35.0, 0.65), "hard": (55.0, 0.42)}

# (archetype, how many). Sixteen candidates, enough for the cohort rules (eight or more).
PLAN = (
    ("honest", 7),
    ("honest_fast", 2),
    ("honest_tech", 2),
    ("tab_lookup", 2),
    ("copier", 1),
    ("answer_runner", 1),
    ("logging_blocker", 1),
)
# Two people also have a long muted or silent stretch (context for a reviewer, never a flag).
MIC_SILENT = {("honest", 3), ("tab_lookup", 1)}


@dataclass
class Item:
    question: Question
    time_s: float
    correct: bool
    skipped: bool = False
    pre_idle_s: float = 0.0
    focus_losses: list[tuple[float, float]] = field(default_factory=list)  # (offset, length)
    copies: list[tuple[float, int]] = field(default_factory=list)  # (offset, length)


@dataclass
class SimSummary:
    created: bool
    sitting_id: int | None
    candidates: int = 0
    flags: FlagRun | None = None
    by_archetype: dict[str, str] = field(default_factory=dict)


# ----------------------------------------------------------------------------------- building


def _pick_questions(rng: random.Random, by_section: dict[str, list[Question]]) -> list[Question]:
    chosen: list[Question] = []
    for section in sorted(by_section):
        chosen += rng.sample(by_section[section], PER_SECTION)
    rng.shuffle(chosen)
    return chosen


def _draw_paper(
    rng: random.Random,
    questions: list[Question],
    archetype: str,
) -> list[Item]:
    speed = 0.62 if archetype == "honest_fast" else 1.0
    ability = rng.gauss(0.5, 0.1) + (0.18 if archetype == "honest_fast" else 0.0)
    items: list[Item] = []
    for question in questions:
        median_s, pct_correct = TYPICAL[question.difficulty or "medium"]
        time_s = max(3.0, rng.lognormvariate(math.log(median_s), 0.32) * speed)
        p_correct = min(0.97, max(0.08, pct_correct + (ability - 0.5) * 0.8))
        items.append(Item(question, time_s, rng.random() < p_correct))

    # Now the scripted behaviour, on positions chosen so the rules have something to find.
    indices = list(range(len(items)))
    middle = indices[2:10]

    if archetype == "tab_lookup":
        for i in rng.sample(middle, 3):
            items[i].time_s = rng.uniform(190, 260)
            items[i].correct = True
            items[i].focus_losses.append((rng.uniform(6, 14), rng.uniform(22, 46)))
    elif archetype == "copier":
        for i in rng.sample(middle, 3):
            items[i].copies.append((rng.uniform(2, 10), rng.randint(110, 320)))
    elif archetype == "answer_runner":
        start = rng.choice([4, 5, 6])
        items[start].pre_idle_s = rng.uniform(88, 120)
        for i in range(start, start + 4):
            items[i].time_s = rng.uniform(4, 8)
            items[i].correct = True
    elif archetype == "honest" and rng.random() < 0.4:
        i = rng.choice(middle)
        items[i].focus_losses.append((rng.uniform(5, 15), rng.uniform(2, 9)))
    elif archetype == "honest_tech" and rng.random() < 0.5:
        i = rng.choice(middle)
        items[i].focus_losses.append((rng.uniform(5, 12), rng.uniform(2, 6)))

    if archetype.startswith("honest") and rng.random() < 0.12:
        pick = rng.choice(indices)
        items[pick].skipped = True
        items[pick].correct = False
        items[pick].time_s = rng.uniform(5, 15)
    return items


def _write_session(
    db: Session,
    rng: random.Random,
    number: int,
    archetype: str,
    ordinal: int,
    sitting: Sitting,
    start_base: datetime,
    questions: list[Question],
    options: dict[str, list[Option]],
    prefix: str,
) -> None:
    candidate_id = f"{prefix}-{number:03d}"
    db.add(
        Candidate(
            id=candidate_id,
            # an unusable hash: nobody has the code, so nobody can start this session
            invite_token_hash=hash_token(f"simulated-{candidate_id}-{rng.getrandbits(96):x}"),
        )
    )

    started_at = start_base + timedelta(seconds=rng.uniform(0, 150))
    # Drawn from the seed, then tied to this sitting and candidate, so a second cohort made with
    # the same seed (the measurement job does this) can never reuse an ID.
    raw = f"{sitting.id}:{candidate_id}:{rng.getrandbits(128):032x}"
    session_id = hashlib.sha256(raw.encode()).hexdigest()[:32]
    items = _draw_paper(rng, questions, archetype)

    events: list[tuple[datetime, str, dict]] = [(started_at, "page_load", {})]
    cursor = started_at + timedelta(seconds=rng.uniform(4, 9))
    quiet: list[tuple[datetime, datetime]] = []  # windows with no heartbeats

    rows: list[SessionQuestion] = []
    for position, item in enumerate(items, start=1):
        if item.pre_idle_s:
            events.append((cursor, "idle_start", {}))
            cursor += timedelta(seconds=item.pre_idle_s)
            events.append((cursor, "idle_end", {"duration_s": round(item.pre_idle_s)}))
        opened = cursor
        answered = opened + timedelta(seconds=item.time_s)
        events.append((opened, "question_opened", {"position": position}))
        for offset, length in item.focus_losses:
            events.append((opened + timedelta(seconds=offset), "focus_lost", {}))
            events.append((opened + timedelta(seconds=offset + length), "focus_returned", {}))
        for offset, length in item.copies:
            events.append(
                (opened + timedelta(seconds=offset), "copy_attempt", {"length": length})
            )
        events.append((answered, "skipped" if item.skipped else "answered", {"position": position}))

        ordered = sorted(options[item.question.id], key=lambda o: o.label)
        correct_option = next(o for o in ordered if o.label == item.question.correct_option)
        wrong = [o for o in ordered if o is not correct_option]
        chosen = None
        if not item.skipped:
            chosen = correct_option if item.correct else rng.choice(wrong)
        order = [o.id for o in ordered]
        rng.shuffle(order)
        rows.append(
            SessionQuestion(
                session_id=session_id,
                position=position,
                question_id=item.question.id,
                option_order=order,
                opened_at=opened,
                answered_at=answered,
                selected_option=chosen.id if chosen else None,
                correct=None if item.skipped else item.correct,
                skipped=item.skipped,
            )
        )
        cursor = answered + timedelta(seconds=rng.uniform(0.5, 1.5))

    finished_at = cursor + timedelta(seconds=1)
    total = (finished_at - started_at).total_seconds()
    self_report = {"had_technical_issues": False, "note": None}
    complaint: tuple[str, str] | None = None

    if archetype == "logging_blocker":
        # heartbeats stop for a minute with no dropped connection and no reload to explain it
        at = started_at + timedelta(seconds=total * rng.uniform(0.35, 0.6))
        quiet.append((at, at + timedelta(seconds=rng.uniform(55, 70))))
    elif archetype == "honest_tech":
        at = started_at + timedelta(seconds=total * rng.uniform(0.25, 0.45))
        lost_for = rng.uniform(14, 38)
        events.append((at, "connection_lost", {}))
        events.append((at + timedelta(seconds=lost_for), "connection_restored", {}))
        quiet.append((at - timedelta(seconds=2), at + timedelta(seconds=lost_for + 2)))
        reload_at = started_at + timedelta(seconds=total * rng.uniform(0.55, 0.7))
        events.append((reload_at, "reload", {}))
        camera_at = started_at + timedelta(seconds=total * rng.uniform(0.7, 0.85))
        events.append((camera_at, "camera_dropped", {"duration_s": round(rng.uniform(20, 45))}))
        self_report = {
            "had_technical_issues": True,
            "note": "My connection dropped for a short while and the page reloaded once.",
        }
        if ordinal == 0:
            complaint = (
                "camera",
                "My camera light went off for a short time in the middle of the test.",
            )

    if (archetype, ordinal) in MIC_SILENT:
        at = started_at + timedelta(seconds=total * rng.uniform(0.3, 0.55))
        length = rng.uniform(70, 96)
        events.append((at, "mic_silent_start", {}))
        events.append(
            (at + timedelta(seconds=length), "mic_silent_end", {"duration_s": round(length)})
        )

    db.add(
        TestSession(
            id=session_id,
            candidate_id=candidate_id,
            sitting_id=sitting.id,
            status="finished",
            created_at=started_at - timedelta(seconds=90),
            started_at=started_at,
            ends_at=started_at + timedelta(seconds=DURATION_S),
            finished_at=finished_at,
            integrity_accepted_at=started_at,
            precheck_passed_at=started_at - timedelta(seconds=40),
            recording_started_at=started_at,
            self_report=self_report,
        )
    )
    db.flush()  # the session row must exist before rows that point at it
    db.add_all(rows)

    for seq, (ts, kind, payload) in enumerate(sorted(events, key=lambda e: e[0]), start=1):
        db.add(
            Event(
                session_id=session_id,
                client_seq=seq,
                type=kind,
                server_ts=ts,
                received_at=ts + timedelta(milliseconds=rng.randint(40, 400)),
                payload=payload or None,
            )
        )

    tick = started_at + timedelta(seconds=10)
    while tick <= finished_at:
        if not any(a <= tick <= b for a, b in quiet):
            db.add(Heartbeat(session_id=session_id, server_ts=tick))
        tick += timedelta(seconds=10)

    if complaint:
        db.add(
            Complaint(
                session_id=session_id,
                category=complaint[0],
                text=complaint[1],
                created_at=finished_at + timedelta(seconds=45),
                status="open",
            )
        )
    db.flush()


# ------------------------------------------------------------------------------- the job itself


def purge(db: Session, name: str = SITTING_NAME, prefix: str = SIM_PREFIX) -> int:
    """Delete the simulated sitting and everything attached. Returns the sessions removed."""
    sitting = db.scalar(select(Sitting).where(Sitting.name == name))
    if sitting is None:
        return 0
    session_ids = list(
        db.scalars(select(TestSession.id).where(TestSession.sitting_id == sitting.id))
    )
    candidate_ids = list(
        db.scalars(
            select(TestSession.candidate_id).where(
                TestSession.sitting_id == sitting.id, TestSession.candidate_id.like(f"{prefix}-%")
            )
        )
    )
    if session_ids:
        db.execute(delete(AuditLog).where(AuditLog.session_id.in_(session_ids)))
        db.execute(delete(SessionQuestion).where(SessionQuestion.session_id.in_(session_ids)))
        db.execute(delete(TestSession).where(TestSession.id.in_(session_ids)))
    if candidate_ids:
        db.execute(delete(Candidate).where(Candidate.id.in_(candidate_ids)))
    db.delete(sitting)
    db.flush()
    return len(session_ids)


def simulate(
    db: Session,
    *,
    seed: int = 1,
    name: str = SITTING_NAME,
    start: datetime = DEFAULT_START,
    prefix: str = SIM_PREFIX,
) -> SimSummary:
    """Write the cohort and compute its flags. Does nothing if the sitting already exists."""
    existing = db.scalar(select(Sitting).where(Sitting.name == name))
    if existing is not None:
        return SimSummary(created=False, sitting_id=existing.id)

    # the bank only: a question an AI wrote for one candidate is never part of a made-up paper
    questions = list(db.scalars(select(Question).where(Question.source != "ai")))
    by_section: dict[str, list[Question]] = {}
    for question in questions:
        by_section.setdefault(question.section, []).append(question)
    if not by_section or any(len(v) < PER_SECTION for v in by_section.values()):
        raise ValueError("the question bank is too small: seed it first (seed_synthetic)")
    options: dict[str, list[Option]] = {}
    for option in db.scalars(select(Option)):
        options.setdefault(option.question_id, []).append(option)

    sitting = Sitting(
        name=name,
        opens_at=start - timedelta(minutes=30),
        closes_at=start + timedelta(hours=2),
        question_count=QUESTION_COUNT,
        duration_s=DURATION_S,
        status="closed",
    )
    db.add(sitting)
    db.flush()

    rng = random.Random(f"simulate-cohort:{seed}")
    summary = SimSummary(created=True, sitting_id=sitting.id)
    number = 0
    for archetype, count in PLAN:
        for ordinal in range(count):
            number += 1
            paper = _pick_questions(rng, by_section)
            _write_session(
                db, rng, number, archetype, ordinal, sitting, start, paper, options, prefix
            )
            summary.by_archetype[f"{prefix}-{number:03d}"] = archetype
    summary.candidates = number
    summary.flags = compute_sitting_flags(db, sitting.id, DEFAULTS)
    return summary


def main(argv: list[str] | None = None) -> None:
    from app.db import SessionLocal

    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--seed", type=int, default=1)
    parser.add_argument("--name", default=SITTING_NAME)
    parser.add_argument("--purge", action="store_true", help="remove the simulated sitting")
    args = parser.parse_args(argv)

    with SessionLocal() as db:
        if args.purge:
            removed = purge(db, args.name)
            db.commit()
            print(f"removed {removed} simulated sessions and everything attached to them")
            return
        try:
            result = simulate(db, seed=args.seed, name=args.name)
        except ValueError as problem:
            db.rollback()
            raise SystemExit(f"not simulated: {problem}") from problem
        db.commit()

    if not result.created:
        print(f"'{args.name}' already exists (sitting {result.sitting_id}); use --purge to redo it")
        return
    flags = result.flags
    print(f"wrote sitting {result.sitting_id}: {result.candidates} sessions")
    if flags:
        print(
            f"flags: {flags.flags} on {flags.flagged} of {flags.sessions} sessions "
            f"(cohort rules {'applied' if flags.cohort_applied else 'skipped'})"
        )
    for candidate, archetype in result.by_archetype.items():
        print(f"  {candidate}  {archetype}")


if __name__ == "__main__":
    main()
