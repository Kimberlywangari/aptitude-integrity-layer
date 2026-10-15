"""Import Cytonn's per-question summary (and, optionally, the question-bank export) into the bank.

The summary columns are the ones the plan names (master plan D8): question_id, section,
correct_option, difficulty_tag, n_candidates, pct_correct, median_s, p25_s, p75_s. A question's
text and four options come from the optional `text` and `option_a` to `option_d` columns of the
summary, or from the bank export, joined on question_id.

PROVISIONAL: Cytonn has not sent either file yet, so the bank export's column names below are
this project's guess. The mapping is in BANK_COLUMNS and the join in `_text_and_options`; if the
real export differs, those are the only two places to change.

A row that passes its checks is imported on its own: one bad row never blocks the others. Existing
questions are updated in place (ids are kept, so earlier sessions still point at them).
"""

import csv
import io
import math
from dataclasses import dataclass, field

from sqlalchemy.orm import Session

from app.errors import ApiError
from app.models import Option, Question, QuestionStats

REQUIRED_COLUMNS = (
    "question_id",
    "section",
    "correct_option",
    "difficulty_tag",
    "n_candidates",
    "pct_correct",
    "median_s",
    "p25_s",
    "p75_s",
)
NUMBER_COLUMNS = ("n_candidates", "pct_correct", "median_s", "p25_s", "p75_s")
BANK_COLUMNS = {"text": "text", "A": "option_a", "B": "option_b", "C": "option_c", "D": "option_d"}
LABELS = ("A", "B", "C", "D")
DIFFICULTIES = ("easy", "medium", "hard")
MAX_ROWS = 5000
ID_MAX = 16
SECTION_MAX = 32

# When a row has no difficulty tag it is read off the share who answered correctly (0 to 100).
EASY_FROM_PCT = 70.0
HARD_BELOW_PCT = 45.0


@dataclass
class Rejected:
    row: int
    question_id: str | None
    reason: str


@dataclass
class ImportResult:
    filename: str
    rows: int
    imported: int = 0
    rejected: list[Rejected] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    difficulty_derived: int = 0


def _read(csv_text: str) -> tuple[list[str], list[dict[str, str]]]:
    rows = list(csv.reader(io.StringIO(csv_text)))
    rows = [r for r in rows if any(cell.strip() for cell in r)]
    if not rows:
        return [], []
    header = [h.strip().lower() for h in rows[0]]
    body = [dict(zip(header, (c.strip() for c in row), strict=False)) for row in rows[1:]]
    return header, body


def _reject(result: "ImportResult", number: int, row: dict[str, str], reason: str) -> None:
    result.rejected.append(Rejected(number, row.get("question_id") or None, reason))


def _derive_difficulty(pct_correct: float) -> str:
    if pct_correct >= EASY_FROM_PCT:
        return "easy"
    if pct_correct < HARD_BELOW_PCT:
        return "hard"
    return "medium"


def _number(raw: str) -> float | None:
    try:
        value = float(raw)
    except ValueError:
        return None
    return value if math.isfinite(value) and value >= 0 else None


def _text_and_options(
    row: dict[str, str], bank_row: dict[str, str] | None
) -> tuple[str | None, dict[str, str]]:
    """The bank export wins over the summary's own columns, field by field."""
    sources = [bank_row, row] if bank_row else [row]

    def pick(column: str) -> str | None:
        for source in sources:
            value = (source.get(column) or "").strip()
            if value:
                return value
        return None

    text = pick(BANK_COLUMNS["text"])
    options = {label: pick(BANK_COLUMNS[label]) for label in LABELS}
    return text, {label: value for label, value in options.items() if value}


def import_summary(
    db: Session, filename: str, summary_csv: str, bank_csv: str | None = None
) -> ImportResult:
    header, rows = _read(summary_csv)
    missing = [c for c in REQUIRED_COLUMNS if c not in header]
    if missing:
        raise ApiError(422, "missing_columns", columns=missing)
    if len(rows) > MAX_ROWS:
        raise ApiError(422, "too_many_rows", max=MAX_ROWS)

    bank_by_id: dict[str, dict[str, str]] = {}
    if bank_csv:
        bank_header, bank_rows = _read(bank_csv)
        if "question_id" not in bank_header:
            raise ApiError(422, "missing_columns", columns=["question_id"], file="bank")
        bank_by_id = {r["question_id"]: r for r in bank_rows if r.get("question_id")}

    result = ImportResult(filename=filename, rows=len(rows))
    seen: set[str] = set()
    supplied_text = bank_csv is not None or "text" in header

    for index, row in enumerate(rows):
        number = index + 2  # 1-based, counting the header row

        question_id = row.get("question_id", "")
        if not question_id:
            _reject(result, number, row, "question_id is empty")
            continue
        if len(question_id) > ID_MAX:
            _reject(result, number, row, f"question_id is longer than {ID_MAX} characters")
            continue
        if question_id in seen:
            _reject(result, number, row, "duplicate question_id")
            continue
        seen.add(question_id)

        correct = row.get("correct_option", "").upper()
        if correct not in LABELS:
            _reject(result, number, row, "correct_option must be A to D")
            continue
        section = row.get("section", "").lower()
        if not section or len(section) > SECTION_MAX:
            _reject(result, number, row, "section is empty or too long")
            continue

        numbers = [_number(row.get(column, "")) for column in NUMBER_COLUMNS]
        if any(n is None for n in numbers):
            _reject(result, number, row, "a number is missing or negative")
            continue
        n_candidates, pct, median, p25, p75 = numbers  # type: ignore[misc]
        if pct > 100:
            _reject(result, number, row, "pct_correct above 100")
            continue
        if not p25 <= median <= p75:
            _reject(result, number, row, "p25 <= median <= p75 does not hold")
            continue

        tag = row.get("difficulty_tag", "").lower()
        if tag and tag not in DIFFICULTIES:
            _reject(result, number, row, "difficulty_tag must be easy, medium or hard")
            continue
        difficulty = tag or _derive_difficulty(pct)

        text, options = _text_and_options(row, bank_by_id.get(question_id))
        question = db.get(Question, question_id)
        if question is None:
            if not text or set(options) != set(LABELS):
                _reject(
                    result,
                    number,
                    row,
                    "a new question needs its text and options A to D "
                    "(add the question-bank export)",
                )
                continue
            question = Question(
                id=question_id,
                section=section,
                difficulty=difficulty,
                correct_option=correct,
                text=text,
            )
            question.options = [Option(label=label, text=options[label]) for label in LABELS]
            db.add(question)
        else:
            question.section = section
            question.difficulty = difficulty
            question.correct_option = correct
            if text:
                question.text = text
            for option in question.options:
                if option.label in options:
                    option.text = options[option.label]

        stats = db.get(QuestionStats, question_id)
        if stats is None:
            stats = QuestionStats(question_id=question_id)
            db.add(stats)
        stats.n = int(n_candidates)
        stats.pct_correct = pct
        stats.median_s = median
        stats.p25_s = p25
        stats.p75_s = p75
        stats.source = "cytonn"

        if not tag:
            result.difficulty_derived += 1
        result.imported += 1

    db.flush()

    if result.difficulty_derived:
        result.warnings.append(
            f"{result.difficulty_derived} rows had no difficulty tag; it was derived from "
            f"pct_correct (easy from {EASY_FROM_PCT:g}, hard below {HARD_BELOW_PCT:g})."
        )
    if not supplied_text:
        result.warnings.append(
            "The summary has no question text and no question-bank export was given, so only "
            "questions already in the bank were updated. Add the bank export to bring new "
            "questions in."
        )
    return result
