"""Write questions for one category and keep only the ones that can be trusted.

No database in here: it takes a writer and gives back finished questions, so every path (a bad
batch, a solver that disagrees, a model that goes away) is tested with a stand-in writer.

For each round it asks the writer for up to BATCH_MAX questions, then
1. tidies and checks each one's form (check.shape),
2. throws out any that repeat a question already on the paper,
3. for numerical questions, settles the key by arithmetic (check.key_from_calculation),
4. puts the options in a shuffled order of its own, so the right answer is wherever chance puts it,
5. shows the questions to the writer again with the key left out, `solves` times, the options in
   a different order each time, and keeps only those it answers the same way every time. One
   agreeing check can be luck or a liking for one position; two in different orders rarely are.
   A numerical question has the arithmetic as a check of its own, so it needs one fewer.
Whatever survives is handed on; whatever is still missing is asked for again, up to a limit.
"""

import random
import time
from collections.abc import Iterator
from dataclasses import dataclass, field

from app.services.qgen import check
from app.services.qgen.categories import Category
from app.services.qgen.check import LABELS, Reject
from app.services.qgen.schema import Written
from app.services.qgen.writers import QuestionWriter, WriterError, WriterUnavailable

BATCH_MAX = 5
EXTRA_ROUNDS = 3  # beyond the rounds a perfect run would need
SOLVES = 2  # independent checks a question must pass, the options in a different order each time


class PaperFailed(Exception):
    """A category could not be filled with questions that passed every check."""


@dataclass
class Report:
    """What happened, for the sample screen and the log: rounds used and why questions were
    thrown away."""

    rounds: int = 0
    asked: int = 0
    accepted: int = 0
    rejected: list[str] = field(default_factory=list)


def arrange(item: check.Shaped, category: str, rng: random.Random) -> Written:
    """Shuffle the options with the server's own random numbers; the key follows its option."""
    order = list(range(len(item.options)))
    rng.shuffle(order)
    return Written(
        category=category,
        difficulty=item.difficulty,
        text=item.text,
        options=tuple(item.options[i] for i in order),
        correct_index=order.index(item.correct_index),
        explanation=item.explanation,
    )


def confirm(
    writer: QuestionWriter, questions: list[Written], solves: int, report: Report
) -> list[Written]:
    """The questions the writer answers the way their key says, `solves` times over. Each pass
    shows the options in a different order (the second reversed, the third as first, and so on), and
    only what passed the last pass is shown in the next, so a doubtful question costs one call."""
    kept = list(questions)
    for attempt in range(max(1, solves)):
        if not kept:
            break
        flipped = attempt % 2 == 1
        shown = [(w.text, list(reversed(w.options)) if flipped else list(w.options)) for w in kept]
        letters = writer.solve(shown)
        passed: list[Written] = []
        for written, letter in zip(kept, letters, strict=True):
            picked = LABELS.index(letter) if letter in LABELS[: len(written.options)] else None
            if picked is not None and flipped:
                picked = len(written.options) - 1 - picked
            if picked == written.correct_index:
                passed.append(written)
            else:
                report.rejected.append("the independent check did not confirm the answer")
        kept = passed
    return kept


def produce(
    writer: QuestionWriter,
    category: Category,
    difficulties: list[str],
    avoid: list[str],
    rng: random.Random,
    report: Report | None = None,
    solves: int = SOLVES,
    deadline: float | None = None,
) -> Iterator[list[Written]]:
    """Yield batches of finished questions until one has been written for each requested
    difficulty. Raises PaperFailed if the rounds run out, WriterUnavailable straight away if the
    model cannot be reached, and PaperFailed if `deadline` (a time.monotonic() value) passes
    between rounds."""
    report = report if report is not None else Report()
    need = list(difficulties)
    avoid_texts = list(avoid)
    seen = [check.words(text) for text in avoid_texts]
    rounds_left = -(-len(need) // BATCH_MAX) + EXTRA_ROUNDS

    while need:
        if deadline is not None and time.monotonic() > deadline:
            raise PaperFailed(f"took too long to write {category.label} questions")
        if rounds_left <= 0:
            reasons = "; ".join(dict.fromkeys(report.rejected[-6:])) or "no usable answer"
            raise PaperFailed(f"could not write enough {category.label} questions ({reasons})")
        rounds_left -= 1
        report.rounds += 1
        ask = need[:BATCH_MAX]
        report.asked += len(ask)
        try:
            raws = writer.write(category, len(ask), ask, avoid_texts)[: len(ask)]
        except WriterUnavailable:
            raise
        except WriterError as problem:
            report.rejected.append(str(problem))
            continue

        shaped: list[check.Shaped] = []
        for index, raw in enumerate(raws):
            try:
                item = check.shape(raw, ask[min(index, len(ask) - 1)])
                if check.is_repeat(item.text, seen):
                    raise Reject("it repeats a question already on the paper")
                if category.numeric:
                    item = check.key_from_calculation(item)
            except Reject as problem:
                report.rejected.append(str(problem))
                continue
            seen.append(check.words(item.text))
            shaped.append(item)
        if not shaped:
            continue

        arranged = [arrange(item, category.key, rng) for item in shaped]
        # the arithmetic has already agreed with a numerical question: it counts as one check
        passes = max(1, solves - 1) if category.numeric else solves
        try:
            accepted = confirm(writer, arranged, passes, report)
        except WriterUnavailable:
            raise
        except WriterError as problem:
            report.rejected.append(f"could not be checked: {problem}")
            # none of this round is trusted; forget its wording so a rewrite is not "a repeat"
            del seen[len(seen) - len(shaped) :]
            continue
        for written in arranged:
            if written not in accepted:
                seen.remove(check.words(written.text))
        if not accepted:
            continue

        for written in accepted:
            slot = written.difficulty if written.difficulty in need else need[0]
            need.remove(slot)
            avoid_texts.append(written.text)
        report.accepted += len(accepted)
        yield accepted
