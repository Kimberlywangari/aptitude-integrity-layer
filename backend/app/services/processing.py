"""Take a closed sitting from raw records to a ranked queue, step by step, timing each step.

The order the pilot used: compute flags, join the video, scan the audio, build packets, rank. The
admin's "Process sitting" button and `scripts.jobs process_sitting` both call `process_sitting`, so
what a person clicks is what was measured.

The button runs it in a background thread inside the API process (a ranking by a local model takes
minutes), and the page asks for progress. The progress is kept in memory, so an API restart forgets
a run that was under way; the work itself is safe to repeat, because every step rewrites its own
results from the stored log. What a finished run produced (the rankings) is in the database.
"""

import logging
import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.clock import Clock, SystemClock
from app.config import Settings, get_settings
from app.models import TestSession
from app.services.audio.silence import detect_silence
from app.services.flags.engine import compute_sitting_flags
from app.services.packets import build_sitting_packets
from app.services.ranking.base import Ranker, RankerError, get_ranker
from app.services.ranking.runner import rank_sitting
from app.services.video import ffmpeg
from app.services.video.assemble import ensure_assembled
from app.services.video.store import LocalVideoStore

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class Step:
    label: str
    seconds: float
    note: str  # counts only, never a name


def process_sitting(
    db: Session,
    sitting_id: int,
    settings: Settings,
    clock: Clock,
    ranker: Ranker | None,
    use_video: bool,
    on_step: Callable[[Step], None] | None = None,
) -> list[Step]:
    """Run every step in order and commit after each, so a stop part way keeps what was finished.
    `ranker=None` is the rules-only run. The video steps need ffmpeg; without it they are noted
    as skipped. Close the sitting first, or the cohort checks do not run."""
    store = LocalVideoStore(settings.video_root_path)
    steps: list[Step] = []

    def timed(label: str, step: Callable[[], str]) -> None:
        started = clock.now()
        note = step()
        done = Step(label, round((clock.now() - started).total_seconds(), 1), note)
        steps.append(done)
        if on_step:
            on_step(done)

    def finished_sessions() -> list[str]:
        return list(
            db.scalars(
                select(TestSession.id).where(
                    TestSession.sitting_id == sitting_id,
                    TestSession.status == "finished",
                    TestSession.video_deleted_at.is_(None),
                )
            )
        )

    def flags() -> str:
        run = compute_sitting_flags(db, sitting_id, clock=clock)
        db.commit()
        cohort = "applied" if run.cohort_applied else "skipped"
        return f"{run.flags} flags on {run.flagged}/{run.sessions} sessions, cohort {cohort}"

    def assemble() -> str:
        segments = sum(
            len(ensure_assembled(db, store, clock, settings, sid).segments)
            for sid in finished_sessions()
        )
        return f"{segments} segments ready"

    def silence() -> str:
        found = sum(detect_silence(db, store, clock, settings, sid) for sid in finished_sessions())
        return f"{found} quiet stretches"

    def packets() -> str:
        built = build_sitting_packets(db, clock, sitting_id)
        db.commit()
        return f"{built} packets"

    def ranking() -> str:
        run = rank_sitting(
            db, sitting_id, ranker, clock, budget_usd=settings.ai_run_budget_usd or None
        )
        db.commit()
        counts = ", ".join(f"{k} {v}" for k, v in sorted(run.statuses.items()))
        who = f"{ranker.name} {ranker.model}" if ranker else "rules only"
        note = f"{run.flagged} ranked by {who} ({counts})"
        if run.spent_usd:
            note += f", about ${run.spent_usd:.2f} spent"
        if run.over_budget:
            note += f"; budget reached, {run.over_budget} left to the rule order"
        return note

    timed("compute flags", flags)
    if use_video:
        timed("assemble video", assemble)
        timed("scan audio", silence)
    else:
        for label in ("assemble video", "scan audio"):
            timed(label, lambda: "skipped (no ffmpeg, or video turned off)")
    timed("build packets", packets)
    timed("rank", ranking)
    return steps


# ------------------------------------------------------------------------------- the button's run


@dataclass
class Run:
    started_at: datetime
    state: str = "running"  # running | done | failed
    steps: list[Step] = field(default_factory=list)
    error: str | None = None
    finished_at: datetime | None = None


_lock = threading.Lock()
_runs: dict[int, Run] = {}  # sitting id -> its latest run


def run_of(sitting_id: int) -> Run | None:
    with _lock:
        return _runs.get(sitting_id)


def launch(sitting_id: int, clock: Clock | None = None) -> bool:
    """Start processing a sitting unless it is already being processed. Returns whether it
    started. Tests replace this (see conftest) and call `_work` inline."""
    clock = clock or SystemClock()
    with _lock:
        current = _runs.get(sitting_id)
        if current is not None and current.state == "running":
            return False
        run = Run(started_at=clock.now())
        _runs[sitting_id] = run
    threading.Thread(
        target=_work, args=(sitting_id, clock, run), name="process-sitting", daemon=True
    ).start()
    return True


def _work(sitting_id: int, clock: Clock, run: Run) -> None:
    from app.db import SessionLocal

    state, error = "done", None
    try:
        settings = get_settings()
        ranker = get_ranker(settings)
        with SessionLocal() as db:
            process_sitting(
                db, sitting_id, settings, clock, ranker, ffmpeg.available(), run.steps.append
            )
    except RankerError as problem:
        state, error = "failed", f"The AI step could not start: {problem}"
    except Exception:
        log.exception("processing sitting %s stopped", sitting_id)
        state, error = "failed", "The run stopped part way. The server log says why."
    # the end time first, so a page that sees "done" always has the time to show with it
    run.error = error
    run.finished_at = clock.now()
    run.state = state
