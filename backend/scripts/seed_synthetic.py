"""Synthetic question bank, question stats, one sitting and 20 invitations.

    python -m scripts.seed_synthetic --seed 42

Idempotent: rows are keyed on question ID, sitting name and candidate number, and rows that
already exist are left alone, so a second run changes nothing (and never overwrites stats that
were later imported from Cytonn).
"""

import argparse
import csv
import hashlib
import hmac
import random
from dataclasses import dataclass, field
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.core.security import format_invite_code, hash_token, invite_code_from_digest
from app.models import Candidate, Option, Question, QuestionStats, Sitting

SECTIONS = ("numerical", "verbal", "logical")
QUESTIONS_PER_SECTION = 20
DIFFICULTY_MIX = ("easy",) * 7 + ("medium",) * 7 + ("hard",) * 6
OPTION_LABELS = ("A", "B", "C", "D")
CANDIDATE_COUNT = 20
SITTING_NAME = "Synthetic sitting 1"

# median seconds and share correct by difficulty (before the +-20% jitter)
STATS_BY_DIFFICULTY = {
    "easy": (25.0, 0.85),
    "medium": (45.0, 0.60),
    "hard": (75.0, 0.35),
}
STATS_N = 400
REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_INVITES_PATH = REPO_ROOT / "data" / "invites.csv"


@dataclass
class Invite:
    candidate_id: str
    token: str
    url: str


@dataclass
class SeedSummary:
    questions_created: int = 0
    options_created: int = 0
    stats_created: int = 0
    candidates_created: int = 0
    sittings_created: int = 0
    sitting_id: int | None = None
    invites: list[Invite] = field(default_factory=list)
    token_mismatches: int = 0


def _invite_token(secret: str, seed: int, number: int) -> str:
    """A short code candidates can type. Deterministic, so `seed` can rebuild data/invites.csv;
    keyed with the session secret. The canonical form has no dash: that is what gets hashed."""
    mac = hmac.new(secret.encode(), f"invite:{seed}:{number}".encode(), hashlib.sha256)
    return invite_code_from_digest(mac.digest())


def seed(
    db: Session,
    *,
    seed: int = 42,
    secret: str | None = None,
    public_base_url: str | None = None,
    invites_path: Path | None = None,
) -> SeedSummary:
    settings = get_settings()
    secret = settings.session_secret if secret is None else secret
    base_url = (public_base_url or settings.public_base_url).rstrip("/")
    rng = random.Random(seed)
    summary = SeedSummary()

    # Draw everything in a fixed order first, so the values never depend on what already exists.
    plan = []
    number = 0
    for section in SECTIONS:
        difficulties = list(DIFFICULTY_MIX)
        rng.shuffle(difficulties)
        for index in range(QUESTIONS_PER_SECTION):
            number += 1
            difficulty = difficulties[index]
            median_base, pct_base = STATS_BY_DIFFICULTY[difficulty]
            median = round(median_base * rng.uniform(0.8, 1.2), 1)
            pct = round(min(0.99, pct_base * rng.uniform(0.8, 1.2)), 3)
            plan.append(
                {
                    "id": f"Q{number:03d}",
                    "section": section,
                    "difficulty": difficulty,
                    "number_in_section": index + 1,
                    "correct_option": rng.choice(OPTION_LABELS),
                    "median_s": median,
                    "pct_correct": pct,
                }
            )

    for item in plan:
        if db.get(Question, item["id"]) is None:
            question = Question(
                id=item["id"],
                section=item["section"],
                difficulty=item["difficulty"],
                correct_option=item["correct_option"],
                text=f"{item['section'].capitalize()} question {item['number_in_section']}: "
                f"placeholder text for {item['id']}.",
            )
            question.options = [
                Option(label=label, text=f"Option {label} for {item['id']}")
                for label in OPTION_LABELS
            ]
            db.add(question)
            summary.questions_created += 1
            summary.options_created += len(OPTION_LABELS)
        if db.get(QuestionStats, item["id"]) is None:
            db.add(
                QuestionStats(
                    question_id=item["id"],
                    n=STATS_N,
                    pct_correct=item["pct_correct"],
                    median_s=item["median_s"],
                    p25_s=round(0.7 * item["median_s"], 1),
                    p75_s=round(1.4 * item["median_s"], 1),
                    source="synthetic",
                )
            )
            summary.stats_created += 1
        db.flush()

    sitting = db.scalar(select(Sitting).where(Sitting.name == SITTING_NAME))
    if sitting is None:
        sitting = Sitting(name=SITTING_NAME, question_count=12, duration_s=1800, status="open")
        db.add(sitting)
        db.flush()
        summary.sittings_created += 1
    summary.sitting_id = sitting.id

    for n in range(1, CANDIDATE_COUNT + 1):
        candidate_id = f"cand-{n:03d}"
        token = _invite_token(secret, seed, n)
        existing = db.get(Candidate, candidate_id)
        if existing is None:
            db.add(Candidate(id=candidate_id, invite_token_hash=hash_token(token)))
            summary.candidates_created += 1
        elif existing.invite_token_hash != hash_token(token):
            # Seeded earlier with another seed or secret: the token can't be reproduced.
            summary.token_mismatches += 1
            continue
        summary.invites.append(
            Invite(candidate_id, token, f"{base_url}/?t={format_invite_code(token)}")
        )

    db.commit()

    if invites_path is not None:
        invites_path.parent.mkdir(parents=True, exist_ok=True)
        with invites_path.open("w", newline="", encoding="utf-8") as fh:
            writer = csv.writer(fh)
            writer.writerow(["candidate_id", "token", "url"])
            for invite in summary.invites:
                # The CSV shows the code the way a candidate types it: XXXX-XXXX.
                code = format_invite_code(invite.token)
                writer.writerow([invite.candidate_id, code, invite.url])
    return summary


def main(argv: list[str] | None = None) -> None:
    from app.db import SessionLocal

    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--invites", type=Path, default=DEFAULT_INVITES_PATH)
    args = parser.parse_args(argv)

    with SessionLocal() as db:
        result = seed(db, seed=args.seed, invites_path=args.invites)

    print(
        f"questions +{result.questions_created}, options +{result.options_created}, "
        f"stats +{result.stats_created}, candidates +{result.candidates_created}, "
        f"sittings +{result.sittings_created} (sitting id {result.sitting_id})"
    )
    print(f"invites written to {args.invites} ({len(result.invites)} rows)")
    if result.token_mismatches:
        print(
            f"warning: {result.token_mismatches} candidates were seeded earlier with another "
            "seed or SESSION_SECRET; their tokens are not in the CSV."
        )


if __name__ == "__main__":
    main()
