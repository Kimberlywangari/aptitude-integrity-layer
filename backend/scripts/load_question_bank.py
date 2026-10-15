"""Load the authored question bank (scripts/question_bank.json) into the database.

    python -m scripts.jobs load_question_bank [--file PATH] [--dry-run] [--force]

Questions are updated in place, keyed on question ID, so sessions that already drew them keep
pointing at them. Text, the four options, the correct option, section and difficulty come from the
file. Statistics are handled honestly:

- A question with `synthetic` statistics gets them recalculated from its (new) difficulty with the
  same table the synthetic seed uses, so a hard question never carries the numbers of an easy one.
  They stay labelled `synthetic`: they are estimates, not measurements.
- A question with `cytonn` statistics is never touched.

These questions are a stand-in until Cytonn supplies its approved bank, so they stay marked as
non-Cytonn, and "retire placeholder questions" in the admin screen will remove them (as intended
once the real bank is imported).

Idempotent. Refuses while a session is in progress (an answer already stored could stop matching
the new answer key) unless --force is given.
"""

import argparse
import json
import random
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import Option, Question, QuestionStats, TestSession
from scripts.seed_synthetic import STATS_BY_DIFFICULTY, STATS_N

# Not under a folder named data/: the repository's .gitignore excludes those (runtime files).
DEFAULT_BANK_PATH = Path(__file__).resolve().parent / "question_bank.json"
LABELS = ("A", "B", "C", "D")
DIFFICULTIES = ("easy", "medium", "hard")
ID_PATTERN = re.compile(r"^Q\d{3}$")
TEXT_MAX = 1000
OPTION_MAX = 300


class BankInUse(Exception):
    """A session is in progress, so changing the answer key could make its answers inconsistent."""


@dataclass
class LoadSummary:
    created: int = 0
    updated: int = 0
    unchanged: int = 0
    stats_created: int = 0
    stats_refreshed: int = 0
    stats_kept_cytonn: int = 0
    by_section: dict[str, dict[str, int]] = field(default_factory=dict)


def validate(data: dict[str, Any]) -> list[str]:
    """Every problem found in the bank file, empty when it is sound."""
    problems: list[str] = []
    questions = data.get("questions")
    if data.get("version") != 1:
        problems.append("version must be 1")
    if not isinstance(questions, list) or not questions:
        return [*problems, "questions must be a non-empty list"]

    seen: set[str] = set()
    for index, q in enumerate(questions):
        qid = q.get("id", f"#{index}")
        where = f"{qid}:"
        if not isinstance(qid, str) or not ID_PATTERN.match(qid):
            problems.append(f"{where} id must look like Q001")
        elif qid in seen:
            problems.append(f"{where} duplicate id")
        seen.add(str(qid))

        if not str(q.get("section", "")).strip():
            problems.append(f"{where} section is empty")
        if q.get("difficulty") not in DIFFICULTIES:
            problems.append(f"{where} difficulty must be easy, medium or hard")

        text = str(q.get("text", "")).strip()
        if not text:
            problems.append(f"{where} text is empty")
        elif len(text) > TEXT_MAX:
            problems.append(f"{where} text is longer than {TEXT_MAX} characters")

        options = q.get("options")
        if not isinstance(options, dict) or set(options) != set(LABELS):
            problems.append(f"{where} options must be exactly A, B, C and D")
        else:
            texts = [str(options[label]).strip() for label in LABELS]
            if any(not t for t in texts):
                problems.append(f"{where} an option is empty")
            if any(len(t) > OPTION_MAX for t in texts):
                problems.append(f"{where} an option is longer than {OPTION_MAX} characters")
            if len({t.casefold() for t in texts}) != len(texts):
                problems.append(f"{where} two options are the same")

        if q.get("correct") not in LABELS:
            problems.append(f"{where} correct must be A, B, C or D")
        if not str(q.get("explanation", "")).strip():
            problems.append(f"{where} explanation is empty")
    return problems


def _stats_for(question_id: str, difficulty: str) -> dict[str, float | int]:
    """Deterministic: the same question and difficulty always give the same estimate."""
    median_base, pct_base = STATS_BY_DIFFICULTY[difficulty]
    rng = random.Random(f"question-bank:{question_id}")
    median = round(median_base * rng.uniform(0.8, 1.2), 1)
    pct = round(min(0.99, pct_base * rng.uniform(0.8, 1.2)), 3)
    return {
        "n": STATS_N,
        "pct_correct": pct,
        "median_s": median,
        "p25_s": round(0.7 * median, 1),
        "p75_s": round(1.4 * median, 1),
    }


def load_bank(db: Session, data: dict[str, Any], *, force: bool = False) -> LoadSummary:
    problems = validate(data)
    if problems:
        raise ValueError("the question bank is not valid:\n  " + "\n  ".join(problems))

    if not force:
        running = db.scalar(
            select(func.count()).select_from(TestSession).where(TestSession.status == "in_progress")
        )
        if running:
            raise BankInUse(
                f"{running} session(s) are in progress. Let them finish, or pass --force if "
                "you accept that their stored answers may no longer match the answer key."
            )

    summary = LoadSummary()
    for item in data["questions"]:
        qid = item["id"]
        section = item["section"].strip().lower()
        text = item["text"].strip()
        option_text = {label: item["options"][label].strip() for label in LABELS}

        question = db.get(Question, qid)
        if question is None:
            question = Question(
                id=qid,
                section=section,
                difficulty=item["difficulty"],
                correct_option=item["correct"],
                text=text,
            )
            question.options = [Option(label=label, text=option_text[label]) for label in LABELS]
            db.add(question)
            summary.created += 1
        else:
            before = (
                question.section,
                question.difficulty,
                question.correct_option,
                question.text,
                {o.label: o.text for o in question.options},
            )
            question.section = section
            question.difficulty = item["difficulty"]
            question.correct_option = item["correct"]
            question.text = text
            existing = {o.label: o for o in question.options}
            for label in LABELS:
                if label in existing:
                    existing[label].text = option_text[label]
                else:
                    question.options.append(Option(label=label, text=option_text[label]))
            after = (
                question.section,
                question.difficulty,
                question.correct_option,
                question.text,
                {o.label: o.text for o in question.options},
            )
            if before == after:
                summary.unchanged += 1
            else:
                summary.updated += 1

        counts = summary.by_section.setdefault(section, {d: 0 for d in DIFFICULTIES})
        counts[item["difficulty"]] += 1

        stats = db.get(QuestionStats, qid)
        if stats is None:
            estimate = _stats_for(qid, item["difficulty"])
            db.add(QuestionStats(question_id=qid, source="synthetic", **estimate))
            summary.stats_created += 1
        elif stats.source == "synthetic":
            for column, value in _stats_for(qid, item["difficulty"]).items():
                setattr(stats, column, value)
            summary.stats_refreshed += 1
        else:
            summary.stats_kept_cytonn += 1
        db.flush()
    return summary


def main(argv: list[str] | None = None) -> None:
    from app.db import SessionLocal

    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--file", type=Path, default=DEFAULT_BANK_PATH)
    parser.add_argument("--dry-run", action="store_true", help="check and report, change nothing")
    parser.add_argument(
        "--force", action="store_true", help="load even while a session is in progress"
    )
    args = parser.parse_args(argv)

    data = json.loads(args.file.read_text(encoding="utf-8"))
    with SessionLocal() as db:
        try:
            summary = load_bank(db, data, force=args.force)
        except (ValueError, BankInUse) as problem:
            db.rollback()
            raise SystemExit(f"not loaded: {problem}") from problem
        if args.dry_run:
            db.rollback()
        else:
            db.commit()

    verb = "would be" if args.dry_run else "were"
    print(
        f"{summary.created} questions created, {summary.updated} updated, "
        f"{summary.unchanged} unchanged ({verb} applied from {args.file.name})"
    )
    print(
        f"statistics: {summary.stats_refreshed} synthetic estimates recalculated, "
        f"{summary.stats_created} created, {summary.stats_kept_cytonn} Cytonn rows left alone"
    )
    for section, counts in sorted(summary.by_section.items()):
        print(f"  {section:10} " + "  ".join(f"{d} {counts[d]}" for d in DIFFICULTIES))


if __name__ == "__main__":
    main()
