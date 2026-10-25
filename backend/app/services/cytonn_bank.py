"""Cytonn's aptitude questions (GET /sections of their API) into the question bank.

`parse_sections` turns the response into the questions we can score and a list of those we cannot,
with the reason. `load_bank` writes them. Neither touches the network: scripts/fetch_cytonn_bank.py
does that, and fetches the pictures (cytonn_images.py) the questions need.

What arrives is HTML, so each question and answer is turned into plain text first
(question_text.py); a picture leaves a marker, `[[image 1]]`, where it stood. Answers that carry
their own letter ("A. ...") lose it, because the screen draws its own.

Cytonn's ids are kept (`cytonn_id` on questions and options) and a question's own id is
C<cytonn id>, so it cannot clash with Q001 and a re-fetch updates it in place. Options are matched
by their Cytonn id, never by letter: the API returns answers in no fixed order, so letters are given
by sorting on the answer id, and they can shift if Cytonn adds an answer. That is why a question a
session has already drawn is never changed: its answer key must stay what the candidate was scored
against.

Skipped and reported, never guessed: a question with no marking scheme or more than one answer
marked correct, with two answers that read the same (none can be told apart), with a picture inside
an answer, a copy of another question (two copies with opposite keys are both left out, because one
of them is wrong), or whose pictures could not be fetched. No statistics are written: the API has no
per-question timing, and no flag rule uses past candidates' figures anyway.
"""

import hashlib
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.models import Option, Question, QuestionImage, SessionQuestion, TestSession
from app.services.cytonn_images import ImageBlob
from app.services.question_text import strip_option_letters, to_plain

LABELS = "ABCDEFGH"
MIN_OPTIONS = 2
MAX_OPTIONS = len(LABELS)
SECTION_MAX = 32  # questions.section
# Characters. A candidate downloads every question, so long ones are worth a look.
TEXT_WARN = 2000
OPTION_WARN = 500
SAMPLE = 5  # ids quoted next to a warning
PASSAGE_CHARS = 100  # questions in a section that open with the same this many characters share one

_EMPHASIS = re.compile(r"<(u|strong|em|b|i)\b")

# Anything that still looks like markup once converted is a surprise worth reporting.
_MARKUP = re.compile(r"</?[a-zA-Z][^>]*>|&[a-zA-Z]+;|&#\d+;")


class BankInUse(Exception):
    """A session is in progress, so the bank should not change under it."""


@dataclass(frozen=True)
class ParsedQuestion:
    cytonn_id: int
    section: str
    text: str
    options: tuple[tuple[int, str], ...]  # (Cytonn answer id, text), sorted by answer id
    correct_answer_id: int
    images: tuple[str, ...] = ()  # addresses, in the order of the [[image N]] markers in the text
    passage_key: str | None = None
    # Which emphasis tags (underline, bold, italic) the original had. Plain text loses them, so they
    # are kept only to tell a copy of a question from a look-alike that differs by emphasis.
    marks: tuple[str, ...] = ()

    @property
    def id(self) -> str:
        return f"C{self.cytonn_id}"


@dataclass
class ParsedBank:
    questions: list[ParsedQuestion] = field(default_factory=list)
    skipped: list[tuple[int | None, str]] = field(default_factory=list)  # (Cytonn id, reason)
    warnings: list[str] = field(default_factory=list)
    minutes: dict[str, float | None] = field(default_factory=dict)  # section -> per question

    @property
    def images_needed(self) -> list[str]:
        return sorted({url for q in self.questions for url in q.images})


@dataclass
class LoadResult:
    created: int = 0
    updated: int = 0
    unchanged: int = 0
    images_stored: int = 0
    no_image: list[int] = field(default_factory=list)  # left out: a picture was not available
    kept_used: list[int] = field(default_factory=list)  # differ from Cytonn, but already drawn
    missing_upstream: list[int] = field(default_factory=list)  # ours, no longer in Cytonn's list
    by_section: dict[str, int] = field(default_factory=dict)


def _as_int(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.strip().isdigit():
        return int(value)
    return None


def _minutes(value: Any) -> float | None:
    try:
        minutes = float(value)
    except (TypeError, ValueError):
        return None
    return minutes if minutes > 0 else None


def passage_key(text: str) -> str | None:
    """Questions that hang off one reading passage open with the same words. None for a short
    question, which has no passage to share."""
    if len(text) < PASSAGE_CHARS:
        return None
    opening = " ".join(text[:PASSAGE_CHARS].casefold().split())
    return hashlib.sha1(opening.encode()).hexdigest()[:16]


def _question(raw: Any, section: str) -> tuple[int | None, "ParsedQuestion | str"]:
    """The question, or the reason it cannot be used."""
    if not isinstance(raw, dict):
        return None, "a question is not an object"
    cytonn_id = _as_int(raw.get("id"))
    if cytonn_id is None:
        return None, "a question has no numeric id"
    original = str(raw.get("question") or "")
    text, pictures = to_plain(original)
    if not text:
        return cytonn_id, "the question has no text"
    if any(url is None for url in pictures):
        return cytonn_id, "a picture has no usable web address"
    images = tuple(url for url in pictures if url)
    answers = raw.get("answers")
    if not isinstance(answers, list):
        return cytonn_id, "the question has no answers"

    options: list[tuple[int, str]] = []
    correct: list[int] = []
    for answer in answers:
        answer_id = _as_int(answer.get("id")) if isinstance(answer, dict) else None
        answer_text, answer_pictures = (
            to_plain(str(answer.get("answer") or "")) if isinstance(answer, dict) else ("", [])
        )
        if answer_id is None or not answer_text:
            return cytonn_id, "an answer has no id or no text"
        if answer_pictures:
            return cytonn_id, "an answer contains a picture"
        options.append((answer_id, answer_text))
        if answer.get("is_correct") in (True, 1):
            correct.append(answer_id)

    if len(options) < MIN_OPTIONS:
        return cytonn_id, f"fewer than {MIN_OPTIONS} answers"
    if len(options) > MAX_OPTIONS:
        return cytonn_id, f"more than {MAX_OPTIONS} answers"
    if len({answer_id for answer_id, _ in options}) != len(options):
        return cytonn_id, "two answers share an id"
    if not correct:
        return cytonn_id, "no marking scheme (no answer is marked correct)"
    if len(correct) > 1:
        return cytonn_id, "more than one answer is marked correct"
    options.sort()
    plain = strip_option_letters([text for _, text in options])
    options = [(answer_id, text) for (answer_id, _), text in zip(options, plain, strict=True)]
    if len({text.casefold() for _, text in options}) < len(options):
        return cytonn_id, "two answers have the same text, so they cannot be told apart"
    marks = tuple(sorted(_EMPHASIS.findall(original)))
    return cytonn_id, ParsedQuestion(
        cytonn_id, section, text, tuple(options), correct[0], images, passage_key(text), marks
    )


def _warn(bank: ParsedBank, ids: list[int], message: str) -> None:
    if ids:
        shown = ", ".join(str(i) for i in ids[:SAMPLE]) + (", ..." if len(ids) > SAMPLE else "")
        bank.warnings.append(f"{len(ids)} question(s) {message} (Cytonn ids {shown})")


def _right_answer_text(question: ParsedQuestion) -> str:
    return next(t for i, t in question.options if i == question.correct_answer_id).casefold()


def _drop_copies(bank: ParsedBank) -> None:
    """One of each question that appears under two ids. If the copies disagree about the answer,
    none is kept: one of them is wrong, and nobody here can say which."""
    groups: dict[tuple[Any, ...], list[ParsedQuestion]] = {}
    for q in bank.questions:
        shape = (
            q.section,
            q.text,
            q.images,
            q.marks,
            tuple(sorted(t.casefold() for _, t in q.options)),
        )
        groups.setdefault(shape, []).append(q)
    drop: set[int] = set()
    for copies in groups.values():
        if len(copies) < 2:
            continue
        copies.sort(key=lambda q: q.cytonn_id)
        if len({_right_answer_text(q) for q in copies}) > 1:
            for q in copies:
                drop.add(q.cytonn_id)
                reason = "its copy under another id has a different answer"
                bank.skipped.append((q.cytonn_id, reason))
            continue
        for q in copies[1:]:
            drop.add(q.cytonn_id)
            bank.skipped.append((q.cytonn_id, f"a copy of question {copies[0].cytonn_id}"))
    bank.questions = [q for q in bank.questions if q.cytonn_id not in drop]


def parse_sections(payload: Any) -> ParsedBank:
    data = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(data, list):
        raise ValueError('unexpected response: expected {"data": [sections]}')

    bank = ParsedBank()
    seen: set[int] = set()
    marked_up: list[int] = []
    long_text: list[int] = []
    long_option: list[int] = []

    for raw_section in data:
        if not isinstance(raw_section, dict):
            bank.skipped.append((None, "a section is not an object"))
            continue
        section = str(raw_section.get("name") or "").strip().lower()
        raw_questions = raw_section.get("questions") or []
        if not section or len(section) > SECTION_MAX:
            reason = f"the section name is empty or longer than {SECTION_MAX} characters"
            for raw in raw_questions:
                cytonn_id = _as_int(raw.get("id")) if isinstance(raw, dict) else None
                bank.skipped.append((cytonn_id, reason))
            continue
        bank.minutes[section] = _minutes(raw_section.get("time_per_question"))

        for raw in raw_questions:
            cytonn_id, parsed = _question(raw, section)
            if isinstance(parsed, str):
                bank.skipped.append((cytonn_id, parsed))
                continue
            if parsed.cytonn_id in seen:
                bank.skipped.append((parsed.cytonn_id, "the question appears twice"))
                continue
            seen.add(parsed.cytonn_id)
            bank.questions.append(parsed)

            texts = [parsed.text] + [text for _, text in parsed.options]
            if any(_MARKUP.search(text) for text in texts):
                marked_up.append(parsed.cytonn_id)
            if len(parsed.text) > TEXT_WARN:
                long_text.append(parsed.cytonn_id)
            if any(len(text) > OPTION_WARN for _, text in parsed.options):
                long_option.append(parsed.cytonn_id)

    _drop_copies(bank)
    _warn(bank, marked_up, "still contain HTML tags or entities after conversion")
    _warn(bank, long_text, f"have text over {TEXT_WARN} characters")
    _warn(bank, long_option, f"have an answer over {OPTION_WARN} characters")
    bank.questions.sort(key=lambda q: (q.section, q.cytonn_id))
    return bank


def _shape(
    section: str,
    text: str,
    correct: str,
    options: list[tuple[int, str, str]],
    images: tuple[str, ...],
) -> tuple[Any, ...]:
    """What makes a question the same as Cytonn's: compared, never written."""
    return (section, text, correct, tuple(sorted(options)), images)


def _options(wanted: list[tuple[int, str, str]]) -> list[Option]:
    return [Option(cytonn_id=aid, label=label, text=text) for aid, label, text in wanted]


def _pictures(urls: tuple[str, ...], blobs: Mapping[str, ImageBlob]) -> list[QuestionImage]:
    return [
        QuestionImage(
            position=position,
            content_type=blobs[url].content_type,
            sha256=blobs[url].sha256,
            source_url=url,
            data=blobs[url].data,
        )
        for position, url in enumerate(urls, start=1)
    ]


def load_bank(
    db: Session,
    bank: ParsedBank,
    *,
    force: bool = False,
    images: Mapping[str, ImageBlob] | None = None,
) -> LoadResult:
    """Write the parsed questions. `images` holds the fetched pictures by address; a question whose
    pictures are neither in it nor already stored with the question is left out and reported."""
    if not force:
        running = db.scalar(
            select(func.count()).select_from(TestSession).where(TestSession.status == "in_progress")
        )
        if running:
            raise BankInUse(
                f"{running} session(s) are in progress. Let them finish, or pass --force if you "
                "accept that a question could change under a candidate who has not reached it."
            )

    blobs: Mapping[str, ImageBlob] = images if images is not None else {}
    result = LoadResult()
    wanted_ids = [q.cytonn_id for q in bank.questions]
    existing = {
        q.cytonn_id: q
        for q in db.scalars(
            select(Question)
            .options(selectinload(Question.options), selectinload(Question.images))
            .where(Question.cytonn_id.in_(wanted_ids))
        )
    }
    drawn: set[str] = set()
    if existing:
        drawn = set(
            db.scalars(
                select(SessionQuestion.question_id)
                .where(SessionQuestion.question_id.in_([q.id for q in existing.values()]))
                .distinct()
            )
        )

    for item in bank.questions:
        label_of = {answer_id: LABELS[i] for i, (answer_id, _) in enumerate(item.options)}
        correct = label_of[item.correct_answer_id]
        wanted = [(answer_id, label_of[answer_id], text) for answer_id, text in item.options]
        question = existing.get(item.cytonn_id)
        stored = tuple(i.source_url for i in question.images) if question else ()

        have_pictures = stored == item.images or all(url in blobs for url in item.images)
        if not have_pictures:
            result.no_image.append(item.cytonn_id)
            continue
        result.by_section[item.section] = result.by_section.get(item.section, 0) + 1

        if question is None:
            question = Question(
                id=item.id,
                cytonn_id=item.cytonn_id,
                section=item.section,
                correct_option=correct,
                text=item.text,
                source="cytonn",
                passage_key=item.passage_key,
            )
            question.options = _options(wanted)
            question.images = _pictures(item.images, blobs)
            result.images_stored += len(item.images)
            db.add(question)
            result.created += 1
            continue

        have = _shape(
            question.section,
            question.text,
            question.correct_option,
            [(o.cytonn_id or 0, o.label, o.text) for o in question.options],
            stored,
        )
        question.passage_key = item.passage_key  # grouping only: never changes what is scored
        if have == _shape(item.section, item.text, correct, wanted, item.images):
            question.source = "cytonn"
            result.unchanged += 1
        elif question.id in drawn:
            result.kept_used.append(item.cytonn_id)
        else:
            question.section = item.section
            question.text = item.text
            question.correct_option = correct
            question.source = "cytonn"
            # delete first: a new letter must not meet the old row's (question, letter) pair
            question.options.clear()
            new_pictures = stored != item.images  # only then are the stored ones replaced
            if new_pictures:
                question.images.clear()
            db.flush()
            question.options.extend(_options(wanted))
            if new_pictures:
                question.images.extend(_pictures(item.images, blobs))
                result.images_stored += len(item.images)
            result.updated += 1

    result.missing_upstream = sorted(
        db.scalars(
            select(Question.cytonn_id).where(
                Question.cytonn_id.is_not(None), Question.cytonn_id.not_in(wanted_ids)
            )
        )
    )
    db.flush()
    return result
