"""Check that a flag lands where it should in the video (the "within 2 seconds" criterion).

    python -m scripts.jobs video_offset --sheet cues.csv

Run a test, do a planted action at a known moment, then open the candidate in the reviewer app,
jump to the flag and note the second *in the video* where the cue is seen or heard. One row per
action: candidate_id, flag_id (such as F3), segment (0 for the first part) and cue_s. The jump
starts 5 seconds before the flag, so the cue should sit about 5 seconds after it; this prints the
error for each row and whether it is within 2 seconds.
"""

import argparse
import csv
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy.orm import Session

from app.clock import SystemClock
from app.config import get_settings
from app.services import review as review_service
from app.services.video.seek import LEAD_S
from app.services.video.store import LocalVideoStore

TOLERANCE_S = 2.0


@dataclass
class Cue:
    candidate_id: str
    flag_id: str
    segment: int
    cue_s: float


@dataclass
class Offset:
    cue: Cue
    seek_s: float | None
    error_s: float | None
    note: str

    @property
    def ok(self) -> bool:
        return self.error_s is not None and abs(self.error_s) <= TOLERANCE_S


def read_cues(path: Path) -> list[Cue]:
    with path.open(newline="", encoding="utf-8-sig") as handle:
        rows = list(csv.DictReader(handle))
    needed = {"candidate_id", "flag_id", "segment", "cue_s"}
    if not rows or not needed <= set(rows[0]):
        raise SystemExit("the sheet needs the columns " + ", ".join(sorted(needed)))
    return [
        Cue(r["candidate_id"].strip(), r["flag_id"].strip(), int(r["segment"]), float(r["cue_s"]))
        for r in rows
    ]


def measure(db: Session, video: review_service.VideoContext, cues: list[Cue]) -> list[Offset]:
    details: dict[str, dict] = {}
    out = []
    for cue in cues:
        if cue.candidate_id not in details:
            details[cue.candidate_id] = review_service.candidate_detail(
                db, cue.candidate_id, None, video=video
            )
        flag = next((f for f in details[cue.candidate_id]["flags"] if f["id"] == cue.flag_id), None)
        if flag is None:
            out.append(Offset(cue, None, None, "no such flag"))
        elif flag["video_seek"] is None:
            out.append(Offset(cue, None, None, "no video at that moment"))
        elif flag["video_seek"]["segment"] != cue.segment:
            part = flag["video_seek"]["segment"]
            out.append(Offset(cue, None, None, f"the jump lands in part {part}"))
        else:
            seek = flag["video_seek"]["seek_s"]
            out.append(Offset(cue, seek, cue.cue_s - (seek + LEAD_S), ""))
    return out


def main(argv: list[str] | None = None) -> None:
    from app.db import SessionLocal

    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--sheet", type=Path, required=True)
    args = parser.parse_args(argv)
    settings = get_settings()
    video = review_service.VideoContext(
        LocalVideoStore(settings.video_root_path), SystemClock(), settings, reviewer_id=0
    )
    cues = read_cues(args.sheet)

    with SessionLocal() as db:
        offsets = measure(db, video, cues)
    for item in offsets:
        label = f"{item.cue.candidate_id} {item.cue.flag_id}"
        if item.error_s is None:
            print(f"{label:<18} FAIL  {item.note}")
        else:
            verdict = "ok  " if item.ok else "FAIL"
            print(f"{label:<18} {verdict}  error {item.error_s:+.1f} s (jump {item.seek_s:.1f} s)")
    passed = sum(1 for o in offsets if o.ok)
    print(f"{passed} of {len(offsets)} within {TOLERANCE_S:g} s")


if __name__ == "__main__":
    main()
